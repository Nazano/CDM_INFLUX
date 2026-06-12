from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timezone
from typing import Any

from app.config import Settings, get_settings
from app.extraction.predictions import extract_predictions
from app.extraction.transcripts import extract_transcript
from app.ingestion.schedule import build_matches, build_teams, build_youtube_search_queries, load_schedule
from app.ingestion.youtube import build_youtube_source
from app.models.entities import Channel, Creator, Match, Prediction, Video
from app.storage.database import Database
from app.storage.repositories import Repository

logger = logging.getLogger(__name__)

_SEARCH_CHANNEL_ID = "_search"
_SEARCH_CREATOR_ID = "_search_creator"
_TBD_PLACEHOLDER = "à déterminer"


def _ensure_search_placeholders(repository: Repository) -> None:
    """Upsert a synthetic creator/channel used for search-based videos."""
    repository.upsert_creator(
        Creator(id=_SEARCH_CREATOR_ID, name="Recherche YouTube", language="fr")
    )
    repository.upsert_channel(
        Channel(
            id=_SEARCH_CHANNEL_ID,
            creator_id=_SEARCH_CREATOR_ID,
            name="Recherche YouTube",
            url="https://www.youtube.com",
            language="fr",
        )
    )


def score_video_relevance(video_payload: dict[str, Any], match: Match) -> float:
    """
    Compute a relevance score [0..1] for a video relative to a match.
    Factors: team names in title/description, recency vs match date.
    """
    title = (video_payload.get("title") or "").lower()
    description = (video_payload.get("description") or "").lower()
    text = title + " " + description

    home = (match.metadata.get("home_team_name") or "").lower()
    away = (match.metadata.get("away_team_name") or "").lower()

    score = 0.0
    if home and home != _TBD_PLACEHOLDER and home in text:
        score += 0.35
    if away and away != _TBD_PLACEHOLDER and away in text:
        score += 0.35

    # Bonus if both teams are in the title specifically
    if home and away and home != _TBD_PLACEHOLDER and home in title and away in title:
        score += 0.15

    # Recency bonus: videos published within 7 days before the match date get bonus
    if match.scheduled_at and video_payload.get("publish_date"):
        try:
            publish_dt: datetime
            raw_pub = video_payload["publish_date"]
            if isinstance(raw_pub, str):
                publish_dt = datetime.fromisoformat(raw_pub.replace("Z", "+00:00"))
            else:
                publish_dt = raw_pub
            if publish_dt.tzinfo is None:
                publish_dt = publish_dt.replace(tzinfo=UTC)
            match_dt = match.scheduled_at
            if match_dt.tzinfo is None:
                match_dt = match_dt.replace(tzinfo=UTC)
            delta_days = (match_dt - publish_dt).total_seconds() / 86400
            if 0 <= delta_days <= 7:
                score += 0.15
            elif -1 <= delta_days < 0:
                # published just after match start – still relevant
                score += 0.05
        except Exception:
            pass

    return min(1.0, score)


def fetch_and_store_videos_for_match(
    match: Match,
    repository: Repository,
    source: Any,
    max_results_per_query: int = 5,
) -> int:
    """Search YouTube for videos related to the given match and store them with relevance scores."""
    queries = build_youtube_search_queries(match)
    if not queries:
        return 0

    _ensure_search_placeholders(repository)

    seen_video_ids: set[str] = set()
    stored = 0

    for query, language in queries:
        try:
            raw_videos = source.search_videos_by_query(query, language, max_results_per_query)
        except Exception as exc:
            logger.warning("YouTube search failed for query '%s': %s", query, exc)
            continue

        for raw in raw_videos:
            vid_id = raw.get("video_id", "")
            if not vid_id or vid_id in seen_video_ids:
                continue
            seen_video_ids.add(vid_id)

            # Use a synthetic channel for search results
            raw["channel_id"] = _SEARCH_CHANNEL_ID

            # Build and store the Video entity
            channel = Channel(
                id=_SEARCH_CHANNEL_ID,
                creator_id=_SEARCH_CREATOR_ID,
                name="Recherche YouTube",
                url="https://www.youtube.com",
                language=language,
            )
            try:
                video = Video(
                    id=f"video-{vid_id}",
                    channel_id=_SEARCH_CHANNEL_ID,
                    creator_id=_SEARCH_CREATOR_ID,
                    video_id=vid_id,
                    video_url=raw["video_url"],
                    title=raw["title"],
                    description=raw.get("description", ""),
                    publish_date=datetime.fromisoformat(
                        raw["publish_date"].replace("Z", "+00:00")
                    ) if isinstance(raw.get("publish_date"), str) else datetime.now(UTC),
                    language=language,
                    duration_seconds=raw.get("duration_seconds"),
                    is_world_cup_related=True,
                    source_payload=raw,
                )
            except Exception as exc:
                logger.warning("Cannot build Video for %s: %s", vid_id, exc)
                continue

            repository.upsert_video(video)
            relevance = score_video_relevance(raw, match)
            repository.link_video_to_match(match.id, video.id, relevance)
            stored += 1

    return stored


def analyze_videos_for_match(
    match_id: str,
    repository: Repository,
    video_ids: list[str] | None = None,
) -> dict[str, int]:
    """
    Download transcripts and extract predictions for videos linked to a match.
    If video_ids is provided, only process those videos; otherwise process all linked videos.
    Returns counts of transcripts extracted and predictions extracted.
    """
    videos = repository.list_videos_for_match(match_id)
    if video_ids is not None:
        video_id_set = set(video_ids)
        videos = [v for v in videos if v["id"] in video_id_set]

    transcript_count = 0
    prediction_count = 0

    for row in videos:
        vid_id = row["video_id"]
        db_video_id = row["id"]
        language = row.get("language", "fr")

        transcript = extract_transcript(vid_id, language=language)
        transcript.video_id = db_video_id
        transcript.id = f"transcript-{vid_id}"
        repository.save_transcript(transcript)
        transcript_count += 1

        if transcript.text:
            extracted = extract_predictions(transcript.text)
            prediction = Prediction(
                id=f"prediction-{uuid.uuid4().hex[:12]}",
                video_id=db_video_id,
                transcript_id=transcript.id,
                extractor_version="rules-v1",
                language=language,
                summary=extracted.summary,
                confidence=extracted.confidence,
                raw_json=extracted.model_dump(mode="json"),
            )
            for item in extracted.items:
                item.prediction_id = prediction.id
            repository.save_prediction(prediction, extracted)
            prediction_count += len(extracted.items)

    return {"transcripts": transcript_count, "predictions": prediction_count}


class MatchIngestionPipeline:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.database = Database(self.settings.db_path)
        self.repository = Repository(self.database)
        self.source = build_youtube_source(self.settings)

    def seed_schedule(self, schedule_path=None) -> int:
        from app.config import DEFAULT_DATA_PATH
        path = schedule_path or (DEFAULT_DATA_PATH.parent / "schedule_2026.json")
        if not path.exists():
            logger.warning("Schedule file not found: %s", path)
            return 0
        schedule = load_schedule(path)
        teams = build_teams(schedule)
        for team in teams:
            self.repository.upsert_team(team)
        matches = build_matches(schedule)
        for match in matches:
            self.repository.upsert_match(match)
        return len(matches)

    def seed_schedule_from_remote(self, force: bool = False) -> int:
        """Fetch and store the match schedule from wheniskickoff.com.

        Uses the ``meta`` field of the remote JSON to detect whether the
        dataset has changed since the last successful fetch.  When the data
        is unchanged and *force* is *False*, nothing is written to the
        database and 0 is returned.

        Args:
            force: When *True*, always fetch and upsert even if the cached
                   meta indicates the data has not changed.

        Returns:
            Number of matches upserted, or 0 when no update was needed.
        """
        from app.ingestion.wheniskickoff import fetch_matches_if_updated

        matches, teams, updated = fetch_matches_if_updated(force=force)
        if not updated:
            return 0
        for team in teams:
            self.repository.upsert_team(team)
        for match in matches:
            self.repository.upsert_match(match)
        return len(matches)

    def fetch_videos_for_match(self, match_id: str, max_results_per_query: int = 5) -> int:
        matches = [m for m in self.repository.get_matches() if m["id"] == match_id]
        if not matches:
            return 0
        row = matches[0]
        match = _row_to_match(row)
        return fetch_and_store_videos_for_match(match, self.repository, self.source, max_results_per_query)

    def analyze_match_videos(self, match_id: str, video_ids: list[str] | None = None) -> dict[str, int]:
        return analyze_videos_for_match(match_id, self.repository, video_ids)


def _row_to_match(row: dict) -> Match:
    import json
    meta = {}
    if row.get("metadata_json"):
        try:
            meta = json.loads(row["metadata_json"])
        except Exception:
            pass
    meta["home_team_name"] = row.get("home_team") or meta.get("home_team_name", "")
    meta["away_team_name"] = row.get("away_team") or meta.get("away_team_name", "")
    scheduled_at = None
    if row.get("scheduled_at"):
        try:
            scheduled_at = datetime.fromisoformat(row["scheduled_at"])
        except Exception:
            pass
    return Match(
        id=row["id"],
        tournament_stage=row["tournament_stage"],
        home_team_id=None,
        away_team_id=None,
        scheduled_at=scheduled_at,
        metadata=meta,
    )
