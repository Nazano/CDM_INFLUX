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
from app.models.entities import AnalysisArtifact, AnalysisRun, AnalysisRunStep, AnalysisStepLog, Channel, Creator, Match, Prediction, Video
from app.storage.database import Database
from app.storage.repositories import Repository

logger = logging.getLogger(__name__)

_SEARCH_CHANNEL_ID = "_search"
_SEARCH_CREATOR_ID = "_search_creator"
_TBD_PLACEHOLDER = "à déterminer"
_ANALYSIS_STEPS = [
    ("search", "🔍 Recherche YouTube"),
    ("transcripts", "📄 Transcription"),
    ("predictions", "🧠 Extraction pronostics"),
    ("finalize", "✅ Finalisation"),
]


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
) -> dict[str, Any]:
    """Search YouTube for videos related to the given match and store them with relevance scores."""
    queries = build_youtube_search_queries(match)
    if not queries:
        return {"stored": 0, "queries": [], "videos": []}

    _ensure_search_placeholders(repository)

    seen_video_ids: set[str] = set()
    stored = 0
    query_summaries: list[dict[str, Any]] = []
    stored_videos: list[dict[str, Any]] = []

    for query, language in queries:
        query_summary = {"query": query, "language": language, "found": 0, "stored": 0, "skipped": []}
        try:
            raw_videos = source.search_videos_by_query(query, language, max_results_per_query)
        except Exception as exc:
            logger.warning("YouTube search failed for query '%s': %s", query, exc)
            query_summary["error"] = str(exc)
            query_summaries.append(query_summary)
            continue

        query_summary["found"] = len(raw_videos)
        for raw in raw_videos:
            vid_id = raw.get("video_id", "")
            if not vid_id or vid_id in seen_video_ids:
                query_summary["skipped"].append(
                    {
                        "video_id": vid_id or "unknown",
                        "reason": "duplicate_or_missing_video_id",
                        "title": raw.get("title", "Vidéo sans titre"),
                    }
                )
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
                query_summary["skipped"].append(
                    {
                        "video_id": vid_id,
                        "reason": "invalid_video_payload",
                        "title": raw.get("title", "Vidéo sans titre"),
                        "error": str(exc),
                    }
                )
                continue

            repository.upsert_video(video)
            relevance = score_video_relevance(raw, match)
            repository.link_video_to_match(match.id, video.id, relevance)
            stored += 1
            query_summary["stored"] += 1
            stored_videos.append(
                {
                    "video_id": video.id,
                    "youtube_video_id": video.video_id,
                    "title": video.title,
                    "language": language,
                    "relevance_score": round(relevance, 2),
                }
            )
        query_summaries.append(query_summary)

    return {"stored": stored, "queries": query_summaries, "videos": stored_videos}


def extract_transcripts_for_match(
    match_id: str,
    repository: Repository,
    video_ids: list[str] | None = None,
    *,
    transcripts_enabled: bool = True,
) -> dict[str, Any]:
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
    unavailable_count = 0
    error_count = 0
    videos_summary: list[dict[str, Any]] = []

    for row in videos:
        vid_id = row["video_id"]
        db_video_id = row["id"]
        language = row.get("language", "fr")

        transcript = extract_transcript(vid_id, language=language, enabled=transcripts_enabled)
        transcript.video_id = db_video_id
        transcript.id = f"transcript-{vid_id}"
        repository.save_transcript(transcript)
        transcript_count += 1
        if transcript.status == "unavailable":
            unavailable_count += 1
        if transcript.status == "error":
            error_count += 1

        video_summary = {
            "video_id": db_video_id,
            "youtube_video_id": vid_id,
            "title": row.get("title", vid_id),
            "transcript_status": transcript.status,
            "prediction_items": 0,
            "prediction_summary": None,
            "language": language,
        }
        videos_summary.append(video_summary)

    return {
        "videos_total": len(videos),
        "transcripts": transcript_count,
        "unavailable_transcripts": unavailable_count,
        "error_transcripts": error_count,
        "videos": videos_summary,
    }


def extract_predictions_for_match(
    match_id: str,
    repository: Repository,
    video_ids: list[str] | None = None,
) -> dict[str, Any]:
    videos = repository.list_videos_for_match(match_id)
    if video_ids is not None:
        video_id_set = set(video_ids)
        videos = [video for video in videos if video["id"] in video_id_set]

    prediction_count = 0
    videos_summary: list[dict[str, Any]] = []
    for row in videos:
        detail = repository.get_video_detail(row["id"]) or {}
        transcript = detail.get("transcript") or {}
        language = row.get("language", "fr")
        video_summary = {
            "video_id": row["id"],
            "youtube_video_id": row["video_id"],
            "title": row.get("title", row["video_id"]),
            "transcript_status": transcript.get("status", "unavailable"),
            "prediction_items": 0,
            "prediction_summary": "Aucun transcript exploitable",
            "language": language,
        }
        transcript_text = transcript.get("text")
        if transcript_text:
            extracted = extract_predictions(transcript_text)
            prediction = Prediction(
                id=f"prediction-{uuid.uuid4().hex[:12]}",
                video_id=row["id"],
                transcript_id=transcript.get("id"),
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
            video_summary["prediction_items"] = len(extracted.items)
            video_summary["prediction_summary"] = prediction.summary
        videos_summary.append(video_summary)
    return {
        "videos_total": len(videos),
        "predictions": prediction_count,
        "videos": videos_summary,
    }


def analyze_videos_for_match(
    match_id: str,
    repository: Repository,
    video_ids: list[str] | None = None,
    *,
    transcripts_enabled: bool = True,
) -> dict[str, Any]:
    transcripts = extract_transcripts_for_match(match_id, repository, video_ids, transcripts_enabled=transcripts_enabled)
    predictions = extract_predictions_for_match(match_id, repository, video_ids)
    merged_predictions = {item["video_id"]: item for item in predictions["videos"]}
    merged_videos = []
    for video in transcripts["videos"]:
        prediction = merged_predictions.get(video["video_id"], {})
        merged_videos.append({**video, **prediction, "transcript_status": video["transcript_status"]})
    return {
        **transcripts,
        "predictions": predictions["predictions"],
        "videos": merged_videos,
    }


def _build_analysis_steps(run_id: str) -> list[AnalysisRunStep]:
    return [
        AnalysisRunStep(
            id=f"analysis-step-{run_id}-{step_key}",
            run_id=run_id,
            step_key=step_key,
            step_label=step_label,
            position=index,
        )
        for index, (step_key, step_label) in enumerate(_ANALYSIS_STEPS, start=1)
    ]


def _notify_progress(
    repository: Repository,
    run_id: str,
    progress_callback: Any | None,
) -> None:
    if progress_callback is not None:
        payload = repository.get_analysis_run_detail(run_id)
        if payload:
            progress_callback(payload)


def _active_step_keys(step_filter: str | None) -> set[str]:
    if not step_filter:
        return {step for step, _ in _ANALYSIS_STEPS}
    if step_filter == "search":
        return {"search", "finalize"}
    if step_filter == "transcripts":
        return {"transcripts", "finalize"}
    if step_filter == "predictions":
        return {"predictions", "finalize"}
    return {step for step, _ in _ANALYSIS_STEPS}


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
        return fetch_and_store_videos_for_match(match, self.repository, self.source, max_results_per_query)["stored"]

    def analyze_match_videos(self, match_id: str, video_ids: list[str] | None = None) -> dict[str, int]:
        result = analyze_videos_for_match(match_id, self.repository, video_ids, transcripts_enabled=self.settings.youtube_transcripts_enabled)
        return {"transcripts": result["transcripts"], "predictions": result["predictions"]}

    def schedule_match_analysis(
        self,
        match_id: str,
        *,
        scheduled_for: datetime,
        note: str | None = None,
    ) -> str:
        run_id = f"analysis-run-{uuid.uuid4().hex[:12]}"
        run = AnalysisRun(
            id=run_id,
            match_id=match_id,
            trigger_type="auto",
            status="queued",
            started_at=datetime.now(UTC),
            scheduled_for=scheduled_for,
            note=note,
            metadata={"mode": "full", "scheduled": True},
        )
        self.repository.create_analysis_run(run, _build_analysis_steps(run_id))
        return run_id

    def run_queued_analysis(self, run_id: str, progress_callback: Any | None = None) -> dict[str, Any]:
        run = self.repository.get_analysis_run_detail(run_id)
        if not run:
            raise ValueError(f"Analysis run not found: {run_id}")
        return self.run_match_pipeline(
            run["match_id"],
            trigger_type=run.get("trigger_type", "auto"),
            progress_callback=progress_callback,
            existing_run_id=run_id,
        )

    def run_match_pipeline(
        self,
        match_id: str,
        *,
        trigger_type: str = "manual",
        max_results_per_query: int = 5,
        video_ids: list[str] | None = None,
        step_filter: str | None = None,
        progress_callback: Any | None = None,
        note: str | None = None,
        existing_run_id: str | None = None,
    ) -> dict[str, Any]:
        matches = [m for m in self.repository.get_matches() if m["id"] == match_id]
        if not matches:
            raise ValueError(f"Match not found: {match_id}")

        row = matches[0]
        match = _row_to_match(row)
        run_id = existing_run_id or f"analysis-run-{uuid.uuid4().hex[:12]}"
        active_steps = _active_step_keys(step_filter)
        run_metadata = {
            "mode": "partial" if step_filter else "full",
            "step_filter": step_filter,
            "video_ids": video_ids or [],
            "max_results_per_query": max_results_per_query,
        }

        if existing_run_id is None:
            run = AnalysisRun(
                id=run_id,
                match_id=match_id,
                trigger_type=trigger_type,
                status="queued",
                started_at=datetime.now(UTC),
                note=note,
                metadata=run_metadata,
            )
            self.repository.create_analysis_run(run, _build_analysis_steps(run_id))
        else:
            detail = self.repository.get_analysis_run_detail(run_id)
            metadata = {**(detail.get("metadata", {}) if detail else {}), **run_metadata}
            self.repository.update_analysis_run(run_id, metadata=metadata)

        started_at = datetime.now(UTC)
        self.repository.update_analysis_run(run_id, status="running", started_at=started_at)
        _notify_progress(self.repository, run_id, progress_callback)

        result: dict[str, Any] = {"run_id": run_id, "search": None, "analysis": None, "status": "success"}
        current_step = None
        try:
            for step_key, _ in _ANALYSIS_STEPS:
                current_step = step_key
                if step_key not in active_steps:
                    self.repository.update_analysis_run_step(
                        run_id,
                        step_key,
                        status="skipped",
                        summary="Étape ignorée pour ce rerun.",
                        completed_at=datetime.now(UTC),
                    )
                    continue
                self.repository.update_analysis_run(
                    run_id,
                    current_step_key=step_key,
                )
                self.repository.update_analysis_run_step(
                    run_id,
                    step_key,
                    status="running",
                    started_at=datetime.now(UTC),
                )
                _notify_progress(self.repository, run_id, progress_callback)

                if step_key == "search":
                    search_result = fetch_and_store_videos_for_match(
                        match,
                        self.repository,
                        self.source,
                        max_results_per_query,
                    )
                    result["search"] = search_result
                    self._log_search_step(run_id, search_result)
                    self.repository.save_analysis_artifact(
                        AnalysisArtifact(
                            id=f"analysis-artifact-{uuid.uuid4().hex[:12]}",
                            run_id=run_id,
                            step_id=self.repository.get_analysis_step_id(run_id, "search"),
                            artifact_type="search_results",
                            label="Résultats de recherche",
                            payload={"items": search_result["videos"], "queries": search_result["queries"]},
                        )
                    )
                    self.repository.update_analysis_run_step(
                        run_id,
                        "search",
                        status="success",
                        summary=f"{search_result['stored']} vidéo(s) enregistrée(s).",
                        stats={"stored": search_result["stored"], "queries": len(search_result["queries"])},
                        completed_at=datetime.now(UTC),
                    )
                elif step_key == "transcripts":
                    transcript_result = extract_transcripts_for_match(match_id, self.repository, video_ids, transcripts_enabled=self.settings.youtube_transcripts_enabled)
                    result["analysis"] = {**(result["analysis"] or {}), **transcript_result}
                    self._log_transcript_step(run_id, transcript_result)
                    self.repository.save_analysis_artifact(
                        AnalysisArtifact(
                            id=f"analysis-artifact-{uuid.uuid4().hex[:12]}",
                            run_id=run_id,
                            step_id=self.repository.get_analysis_step_id(run_id, "transcripts"),
                            artifact_type="transcripts",
                            label="Transcripts bruts",
                            payload={
                                "items": [
                                    {
                                        "key": item["video_id"],
                                        "video_id": item["video_id"],
                                        "title": item["title"],
                                        "transcript_status": item["transcript_status"],
                                    }
                                    for item in transcript_result["videos"]
                                ]
                            },
                        )
                    )
                    summary = (
                        f"{transcript_result['transcripts']} transcript(s), "
                        f"{transcript_result['unavailable_transcripts']} indisponible(s), "
                        f"{transcript_result['error_transcripts']} erreur(s)."
                    )
                    transcript_step_status = "failed" if transcript_result["error_transcripts"] else "success"
                    self.repository.update_analysis_run_step(
                        run_id,
                        "transcripts",
                        status=transcript_step_status,
                        summary=summary,
                        stats={
                            "transcripts": transcript_result["transcripts"],
                            "unavailable": transcript_result["unavailable_transcripts"],
                            "errors": transcript_result["error_transcripts"],
                        },
                        completed_at=datetime.now(UTC),
                    )
                    if transcript_step_status == "failed":
                        result["status"] = "failed"
                elif step_key == "predictions":
                    prediction_result = extract_predictions_for_match(match_id, self.repository, video_ids)
                    result["analysis"] = {**(result["analysis"] or {}), **prediction_result}
                    self._log_prediction_step(run_id, prediction_result)
                    self.repository.save_analysis_artifact(
                        AnalysisArtifact(
                            id=f"analysis-artifact-{uuid.uuid4().hex[:12]}",
                            run_id=run_id,
                            step_id=self.repository.get_analysis_step_id(run_id, "predictions"),
                            artifact_type="predictions",
                            label="Pronostics extraits",
                            payload={
                                "items": [
                                    {
                                        "key": item["video_id"],
                                        "video_id": item["video_id"],
                                        "title": item["title"],
                                        "prediction_items": item["prediction_items"],
                                        "prediction_summary": item["prediction_summary"],
                                    }
                                    for item in prediction_result["videos"]
                                ]
                            },
                        )
                    )
                    self.repository.save_analysis_artifact(
                        AnalysisArtifact(
                            id=f"analysis-artifact-{uuid.uuid4().hex[:12]}",
                            run_id=run_id,
                            step_id=self.repository.get_analysis_step_id(run_id, "predictions"),
                            artifact_type="confidence_report",
                            label="Rapport de confiance",
                            payload={
                                "items": [
                                    {
                                        "key": "summary",
                                        "predictions": prediction_result["predictions"],
                                        "videos_total": prediction_result["videos_total"],
                                        "coverage_rate": round(
                                            (prediction_result["predictions"] / prediction_result["videos_total"]) * 100,
                                            1,
                                        ) if prediction_result["videos_total"] else 0.0,
                                    }
                                ]
                            },
                        )
                    )
                    prediction_status = "success"
                    summary = f"{prediction_result['predictions']} pronostic(s) extrait(s)."
                    if not prediction_result["predictions"]:
                        prediction_status = "failed" if prediction_result["videos_total"] else "skipped"
                        summary = "Aucun pronostic extrait."
                        result["status"] = "failed" if prediction_result["videos_total"] else result["status"]
                    self.repository.update_analysis_run_step(
                        run_id,
                        "predictions",
                        status=prediction_status,
                        summary=summary,
                        stats={
                            "predictions": prediction_result["predictions"],
                            "videos_total": prediction_result["videos_total"],
                        },
                        completed_at=datetime.now(UTC),
                    )
                else:
                    final_status = result["status"]
                    final_summary = "Pipeline finalisé avec succès." if final_status == "success" else "Pipeline terminé avec des erreurs."
                    self.repository.update_analysis_run_step(
                        run_id,
                        "finalize",
                        status="success" if final_status == "success" else "failed",
                        summary=final_summary,
                        stats={"status": final_status},
                        completed_at=datetime.now(UTC),
                    )
                _notify_progress(self.repository, run_id, progress_callback)
        except Exception as exc:
            logger.exception("Analysis pipeline failed for match %s", match_id)
            failed_step = current_step or "finalize"
            self.repository.update_analysis_run_step(
                run_id,
                failed_step,
                status="failed",
                summary=str(exc),
                completed_at=datetime.now(UTC),
            )
            if step_id := self.repository.get_analysis_step_id(run_id, failed_step):
                self.repository.append_analysis_step_log(
                    AnalysisStepLog(
                        id=f"analysis-log-{uuid.uuid4().hex[:12]}",
                        step_id=step_id,
                        level="error",
                        message=str(exc),
                        metadata={"exception_type": exc.__class__.__name__},
                    )
                )
            result["status"] = "failed"

        completed_at = datetime.now(UTC)
        self.repository.update_analysis_run(
            run_id,
            status=result["status"],
            current_step_key="finalize",
            completed_at=completed_at,
        )
        _notify_progress(self.repository, run_id, progress_callback)
        detail = self.repository.get_analysis_run_detail(run_id) or {"id": run_id}
        result["detail"] = detail
        return result

    def _log_search_step(self, run_id: str, search_result: dict[str, Any]) -> None:
        step_id = self.repository.get_analysis_step_id(run_id, "search")
        if not step_id:
            return
        for query in search_result["queries"]:
            self.repository.append_analysis_step_log(
                AnalysisStepLog(
                    id=f"analysis-log-{uuid.uuid4().hex[:12]}",
                    step_id=step_id,
                    level="info" if not query.get("error") else "error",
                    message=f"{query['language'].upper()} · {query['query']}",
                    metadata=query,
                )
            )

    def _log_transcript_step(self, run_id: str, analysis_result: dict[str, Any]) -> None:
        step_id = self.repository.get_analysis_step_id(run_id, "transcripts")
        if not step_id:
            return
        for video in analysis_result["videos"]:
            level = "info" if video["transcript_status"] == "available" else "warning"
            self.repository.append_analysis_step_log(
                AnalysisStepLog(
                    id=f"analysis-log-{uuid.uuid4().hex[:12]}",
                    step_id=step_id,
                    level=level,
                    message=f"{video['title']} · transcript {video['transcript_status']}",
                    metadata=video,
                )
            )

    def _log_prediction_step(self, run_id: str, analysis_result: dict[str, Any]) -> None:
        step_id = self.repository.get_analysis_step_id(run_id, "predictions")
        if not step_id:
            return
        for video in analysis_result["videos"]:
            level = "info" if video["prediction_items"] else "warning"
            self.repository.append_analysis_step_log(
                AnalysisStepLog(
                    id=f"analysis-log-{uuid.uuid4().hex[:12]}",
                    step_id=step_id,
                    level=level,
                    message=f"{video['title']} · {video['prediction_items']} pronostic(s)",
                    metadata=video,
                )
            )


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
