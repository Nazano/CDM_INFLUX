from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from app.models.entities import Channel, Creator, ExtractedPredictions, Match, Prediction, PredictionItem, Team, Transcript, Video
from app.storage.database import Database, dumps_json


class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_creator(self, creator: Creator) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO creators (id, name, language, historical_accuracy, weight, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    language = excluded.language,
                    historical_accuracy = excluded.historical_accuracy,
                    weight = excluded.weight,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (creator.id, creator.name, creator.language, creator.historical_accuracy, creator.weight),
            )

    def upsert_channel(self, channel: Channel) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO channels (id, creator_id, name, url, language, region, active, keywords_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    creator_id = excluded.creator_id,
                    name = excluded.name,
                    url = excluded.url,
                    language = excluded.language,
                    region = excluded.region,
                    active = excluded.active,
                    keywords_json = excluded.keywords_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    channel.id,
                    channel.creator_id,
                    channel.name,
                    channel.url,
                    channel.language,
                    channel.region,
                    int(channel.active),
                    dumps_json(channel.keywords),
                ),
            )

    def upsert_team(self, team: Team) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO teams (id, name, code)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    code = excluded.code
                """,
                (team.id, team.name, team.code),
            )

    def upsert_video(self, video: Video) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO videos (
                    id, channel_id, creator_id, video_id, video_url, title, description,
                    publish_date, language, duration_seconds, is_world_cup_related,
                    source_payload_json, reprocess_version, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(video_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    creator_id = excluded.creator_id,
                    video_url = excluded.video_url,
                    title = excluded.title,
                    description = excluded.description,
                    publish_date = excluded.publish_date,
                    language = excluded.language,
                    duration_seconds = excluded.duration_seconds,
                    is_world_cup_related = excluded.is_world_cup_related,
                    source_payload_json = excluded.source_payload_json,
                    reprocess_version = videos.reprocess_version + 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    video.id,
                    video.channel_id,
                    video.creator_id,
                    video.video_id,
                    video.video_url,
                    video.title,
                    video.description,
                    video.publish_date.isoformat(),
                    video.language,
                    video.duration_seconds,
                    int(video.is_world_cup_related),
                    dumps_json(video.source_payload),
                ),
            )

    def save_transcript(self, transcript: Transcript) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO transcripts (
                    id, video_id, status, text, language, segments_json, version, source, extracted_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    text = excluded.text,
                    language = excluded.language,
                    segments_json = excluded.segments_json,
                    version = transcripts.version + 1,
                    source = excluded.source,
                    extracted_at = excluded.extracted_at,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    transcript.id,
                    transcript.video_id,
                    transcript.status,
                    transcript.text,
                    transcript.language,
                    dumps_json([segment.model_dump() for segment in transcript.segments]),
                    transcript.version,
                    transcript.source,
                    transcript.extracted_at.isoformat(),
                ),
            )

    def save_prediction(self, prediction: Prediction, extracted: ExtractedPredictions) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO predictions (
                    id, video_id, transcript_id, extractor_version, language, summary,
                    confidence, raw_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    transcript_id = excluded.transcript_id,
                    extractor_version = excluded.extractor_version,
                    language = excluded.language,
                    summary = excluded.summary,
                    confidence = excluded.confidence,
                    raw_json = excluded.raw_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    prediction.id,
                    prediction.video_id,
                    prediction.transcript_id,
                    prediction.extractor_version,
                    prediction.language,
                    prediction.summary,
                    prediction.confidence,
                    dumps_json(prediction.raw_json),
                    prediction.created_at.isoformat(),
                ),
            )
            conn.execute("DELETE FROM prediction_items WHERE prediction_id = ?", (prediction.id,))
            for item in extracted.items:
                conn.execute(
                    """
                    INSERT INTO prediction_items (
                        id, prediction_id, item_type, subject, value, confidence, rationale,
                        quote, match_id, team_id, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        prediction.id,
                        item.item_type,
                        item.subject,
                        item.value,
                        item.confidence,
                        item.rationale,
                        item.quote,
                        item.match_id,
                        item.team_id,
                        dumps_json(item.metadata),
                    ),
                )

    def get_overview_metrics(self) -> dict[str, Any]:
        with self.database.connection() as conn:
            metrics = {
                "channels": conn.execute("SELECT COUNT(*) FROM channels WHERE active = 1").fetchone()[0],
                "videos": conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0],
                "predictions": conn.execute("SELECT COUNT(*) FROM prediction_items").fetchone()[0],
                "languages": [dict(row) for row in conn.execute("SELECT language, COUNT(*) AS count FROM videos GROUP BY language ORDER BY count DESC")],
            }
        return metrics

    def list_videos(
        self,
        *,
        language: str | None = None,
        channel_id: str | None = None,
        team_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        filters = []
        params: list[Any] = []
        query = """
            SELECT v.id, v.video_id, v.title, v.language, v.publish_date, v.video_url,
                   c.name AS channel_name, p.summary AS prediction_summary
            FROM videos v
            JOIN channels c ON c.id = v.channel_id
            LEFT JOIN predictions p ON p.video_id = v.id
            LEFT JOIN prediction_items pi ON pi.prediction_id = p.id
        """
        if language:
            filters.append("v.language = ?")
            params.append(language)
        if channel_id:
            filters.append("v.channel_id = ?")
            params.append(channel_id)
        if team_filter:
            filters.append("pi.value = ?")
            params.append(team_filter)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " GROUP BY v.id ORDER BY v.publish_date DESC"
        with self.database.connection() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    def get_video_detail(self, video_db_id: str) -> dict[str, Any] | None:
        with self.database.connection() as conn:
            video_row = conn.execute(
                """
                SELECT v.*, c.name AS channel_name, c.url AS channel_url
                FROM videos v JOIN channels c ON c.id = v.channel_id
                WHERE v.id = ?
                """,
                (video_db_id,),
            ).fetchone()
            if not video_row:
                return None
            transcript_row = conn.execute("SELECT * FROM transcripts WHERE video_id = ? ORDER BY updated_at DESC LIMIT 1", (video_db_id,)).fetchone()
            prediction_row = conn.execute("SELECT * FROM predictions WHERE video_id = ? ORDER BY updated_at DESC LIMIT 1", (video_db_id,)).fetchone()
            items = []
            if prediction_row:
                items = [
                    dict(row)
                    for row in conn.execute("SELECT * FROM prediction_items WHERE prediction_id = ? ORDER BY item_type, confidence DESC", (prediction_row["id"],))
                ]
            return {
                "video": dict(video_row),
                "transcript": dict(transcript_row) if transcript_row else None,
                "prediction": dict(prediction_row) if prediction_row else None,
                "prediction_items": items,
            }

    def get_creator_comparison(self) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT c.name AS creator_name, pi.item_type, pi.subject, pi.value, AVG(pi.confidence) AS confidence
                    FROM prediction_items pi
                    JOIN predictions p ON p.id = pi.prediction_id
                    JOIN videos v ON v.id = p.video_id
                    JOIN creators c ON c.id = v.creator_id
                    GROUP BY c.name, pi.item_type, pi.subject, pi.value
                    ORDER BY c.name, pi.item_type
                    """
                )
            ]

    def get_match_consensus(self) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT subject AS match_label, value, COUNT(*) AS picks, ROUND(AVG(confidence), 2) AS avg_confidence
                    FROM prediction_items
                    WHERE item_type IN ('match_winner', 'exact_score')
                    GROUP BY subject, value
                    ORDER BY subject, picks DESC, avg_confidence DESC
                    """
                )
            ]

    def get_creator_reliability(self) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT cr.name AS creator_name,
                           cr.historical_accuracy,
                           cr.weight,
                           COUNT(DISTINCT v.id) AS videos_count,
                           ROUND(AVG(p.confidence), 2) AS avg_prediction_confidence
                    FROM creators cr
                    LEFT JOIN videos v ON v.creator_id = cr.id
                    LEFT JOIN predictions p ON p.video_id = v.id
                    GROUP BY cr.id, cr.name, cr.historical_accuracy, cr.weight
                    ORDER BY cr.historical_accuracy DESC, avg_prediction_confidence DESC
                    """
                )
            ]

    def list_channels(self) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT id, name, language FROM channels WHERE active = 1 ORDER BY name")]

    def is_empty(self) -> bool:
        with self.database.connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0

    def upsert_match(self, match: Match) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO matches (id, tournament_stage, home_team_id, away_team_id, scheduled_at, metadata_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    tournament_stage = excluded.tournament_stage,
                    home_team_id = excluded.home_team_id,
                    away_team_id = excluded.away_team_id,
                    scheduled_at = excluded.scheduled_at,
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    match.id,
                    match.tournament_stage,
                    match.home_team_id,
                    match.away_team_id,
                    match.scheduled_at.isoformat() if match.scheduled_at else None,
                    dumps_json(match.metadata),
                ),
            )

    def get_matches(self) -> list[dict[str, Any]]:
        now_iso = datetime.now(UTC).isoformat()
        with self.database.connection() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT
                        m.id, m.tournament_stage, m.scheduled_at,
                        m.metadata_json,
                        ht.name AS home_team, ht.code AS home_team_code,
                        at.name AS away_team, at.code AS away_team_code,
                        CASE WHEN m.scheduled_at < ? THEN 1 ELSE 0 END AS is_past,
                        (SELECT COUNT(*) FROM match_video_links mvl WHERE mvl.match_id = m.id) AS video_count
                    FROM matches m
                    LEFT JOIN teams ht ON ht.id = m.home_team_id
                    LEFT JOIN teams at ON at.id = m.away_team_id
                    ORDER BY m.scheduled_at
                    """,
                    (now_iso,),
                )
            ]

    def link_video_to_match(self, match_id: str, video_id: str, relevance_score: float) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO match_video_links (match_id, video_id, relevance_score)
                VALUES (?, ?, ?)
                ON CONFLICT(match_id, video_id) DO UPDATE SET
                    relevance_score = excluded.relevance_score,
                    linked_at = CURRENT_TIMESTAMP
                """,
                (match_id, video_id, relevance_score),
            )

    def list_videos_for_match(self, match_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT v.id, v.video_id, v.title, v.language, v.publish_date, v.video_url,
                           c.name AS channel_name, mvl.relevance_score,
                           p.summary AS prediction_summary,
                           t.status AS transcript_status
                    FROM match_video_links mvl
                    JOIN videos v ON v.id = mvl.video_id
                    JOIN channels c ON c.id = v.channel_id
                    LEFT JOIN predictions p ON p.video_id = v.id
                    LEFT JOIN transcripts t ON t.video_id = v.id
                    WHERE mvl.match_id = ?
                    ORDER BY mvl.relevance_score DESC, v.publish_date DESC
                    """,
                    (match_id,),
                )
            ]

    def has_matches(self) -> bool:
        with self.database.connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] > 0
