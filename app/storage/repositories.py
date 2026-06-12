from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from app.models.entities import (
    AnalysisArtifact,
    AnalysisRun,
    AnalysisRunStep,
    AnalysisStepLog,
    Channel,
    Creator,
    ExtractedPredictions,
    Match,
    Prediction,
    PredictionItem,
    Team,
    Transcript,
    Video,
)
from app.storage.database import Database, dumps_json


class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _loads_json(payload: str | None, default: Any) -> Any:
        import json

        if not payload:
            return default
        try:
            return json.loads(payload)
        except Exception:
            return default

    @staticmethod
    def _isoformat(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

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
                "analysis_runs": conn.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0],
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
            WITH latest_predictions AS (
                SELECT p1.id, p1.video_id, p1.summary
                FROM predictions p1
                JOIN (
                    SELECT video_id, MAX(updated_at) AS updated_at
                    FROM predictions
                    GROUP BY video_id
                ) latest ON latest.video_id = p1.video_id AND latest.updated_at = p1.updated_at
            ),
            latest_transcripts AS (
                SELECT t1.video_id, t1.status, t1.extracted_at
                FROM transcripts t1
                JOIN (
                    SELECT video_id, MAX(extracted_at) AS extracted_at
                    FROM transcripts
                    GROUP BY video_id
                ) latest ON latest.video_id = t1.video_id AND latest.extracted_at = t1.extracted_at
            )
            SELECT v.id, v.video_id, v.title, v.language, v.publish_date, v.video_url,
                   c.name AS channel_name, p.summary AS prediction_summary,
                   COALESCE(t.extracted_at, v.updated_at) AS processed_at
            FROM videos v
            JOIN channels c ON c.id = v.channel_id
            LEFT JOIN latest_predictions p ON p.video_id = v.id
            LEFT JOIN latest_transcripts t ON t.video_id = v.id
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
        query += " GROUP BY v.id ORDER BY processed_at DESC"
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

    def list_available_transcripts(self) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    WITH latest_transcripts AS (
                        SELECT t1.*
                        FROM transcripts t1
                        JOIN (
                            SELECT video_id, MAX(updated_at) AS updated_at
                            FROM transcripts
                            GROUP BY video_id
                        ) latest ON latest.video_id = t1.video_id AND latest.updated_at = t1.updated_at
                    )
                    SELECT
                        lt.id,
                        v.id AS video_db_id,
                        v.video_id,
                        v.title AS video_title,
                        lt.text,
                        lt.language,
                        lt.status,
                        lt.source
                    FROM latest_transcripts lt
                    JOIN videos v ON v.id = lt.video_id
                    WHERE lt.status = 'available' AND COALESCE(lt.text, '') != ''
                    ORDER BY lt.updated_at DESC
                    """
                )
            ]

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
                    WITH latest_predictions AS (
                        SELECT p1.id, p1.video_id, p1.confidence
                        FROM predictions p1
                        JOIN (
                            SELECT video_id, MAX(updated_at) AS updated_at
                            FROM predictions
                            GROUP BY video_id
                        ) latest ON latest.video_id = p1.video_id AND latest.updated_at = p1.updated_at
                    ),
                    score_rank AS (
                        SELECT
                            mvl.match_id,
                            pi.value AS predicted_score,
                            COUNT(*) AS score_votes,
                            ROUND(AVG(pi.confidence), 2) AS avg_score_confidence,
                            ROW_NUMBER() OVER (
                                PARTITION BY mvl.match_id
                                ORDER BY COUNT(*) DESC, AVG(pi.confidence) DESC, pi.value
                            ) AS score_rank
                        FROM match_video_links mvl
                        JOIN latest_predictions lp ON lp.video_id = mvl.video_id
                        JOIN prediction_items pi ON pi.prediction_id = lp.id
                        JOIN matches mx ON mx.id = mvl.match_id
                        LEFT JOIN teams htx ON htx.id = mx.home_team_id
                        LEFT JOIN teams atx ON atx.id = mx.away_team_id
                        WHERE pi.item_type = 'exact_score'
                          AND pi.subject IN (
                              COALESCE(htx.name, '') || ' vs ' || COALESCE(atx.name, ''),
                              COALESCE(atx.name, '') || ' vs ' || COALESCE(htx.name, '')
                          )
                        GROUP BY mvl.match_id, pi.value
                    ),
                    latest_analysis_run AS (
                        SELECT ar.match_id,
                               ar.status AS last_analysis_status,
                               ar.current_step_key AS last_analysis_step,
                               ar.completed_at AS last_analysis_completed_at,
                               ROW_NUMBER() OVER (
                                   PARTITION BY ar.match_id
                                   ORDER BY COALESCE(ar.completed_at, ar.started_at) DESC, ar.created_at DESC
                               ) AS run_rank
                        FROM analysis_runs ar
                        WHERE ar.is_ignored = 0
                    )
                    SELECT
                        m.id, m.tournament_stage, m.scheduled_at,
                        m.metadata_json,
                        ht.name AS home_team, ht.code AS home_team_code,
                        at.name AS away_team, at.code AS away_team_code,
                        CASE WHEN m.scheduled_at < ? THEN 1 ELSE 0 END AS is_past,
                        COUNT(DISTINCT mvl.video_id) AS video_count,
                        COUNT(DISTINCT t.video_id) AS analyzed_video_count,
                        COUNT(DISTINCT lp.video_id) AS predicted_video_count,
                        COUNT(DISTINCT lp.id) AS prediction_count,
                        sr.predicted_score,
                        COALESCE(sr.score_votes, 0) AS score_votes,
                        COALESCE(sr.avg_score_confidence, 0) AS avg_score_confidence,
                        lar.last_analysis_status,
                        lar.last_analysis_step,
                        lar.last_analysis_completed_at
                    FROM matches m
                    LEFT JOIN teams ht ON ht.id = m.home_team_id
                    LEFT JOIN teams at ON at.id = m.away_team_id
                    LEFT JOIN match_video_links mvl ON mvl.match_id = m.id
                    LEFT JOIN transcripts t ON t.video_id = mvl.video_id
                    LEFT JOIN latest_predictions lp ON lp.video_id = mvl.video_id
                    LEFT JOIN score_rank sr ON sr.match_id = m.id AND sr.score_rank = 1
                    LEFT JOIN latest_analysis_run lar ON lar.match_id = m.id AND lar.run_rank = 1
                    GROUP BY
                        m.id, m.tournament_stage, m.scheduled_at, m.metadata_json,
                        ht.name, ht.code, at.name, at.code,
                        sr.predicted_score, sr.score_votes, sr.avg_score_confidence,
                        lar.last_analysis_status, lar.last_analysis_step, lar.last_analysis_completed_at
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
                    WITH latest_predictions AS (
                        SELECT p1.id, p1.video_id, p1.summary
                        FROM predictions p1
                        JOIN (
                            SELECT video_id, MAX(updated_at) AS updated_at
                            FROM predictions
                            GROUP BY video_id
                        ) latest ON latest.video_id = p1.video_id AND latest.updated_at = p1.updated_at
                    ),
                    latest_transcripts AS (
                        SELECT t1.video_id, t1.status, t1.extracted_at
                        FROM transcripts t1
                        JOIN (
                            SELECT video_id, MAX(extracted_at) AS extracted_at
                            FROM transcripts
                            GROUP BY video_id
                        ) latest ON latest.video_id = t1.video_id AND latest.extracted_at = t1.extracted_at
                    )
                    SELECT v.id, v.video_id, v.title, v.language, v.publish_date, v.video_url,
                           c.name AS channel_name, mvl.relevance_score,
                           p.summary AS prediction_summary,
                           t.status AS transcript_status,
                           COALESCE(t.extracted_at, v.updated_at) AS processed_at
                    FROM match_video_links mvl
                    JOIN videos v ON v.id = mvl.video_id
                    JOIN channels c ON c.id = v.channel_id
                    LEFT JOIN latest_predictions p ON p.video_id = v.id
                    LEFT JOIN latest_transcripts t ON t.video_id = v.id
                    WHERE mvl.match_id = ?
                    ORDER BY processed_at DESC, mvl.relevance_score DESC
                    """,
                    (match_id,),
                )
            ]

    def create_analysis_run(self, run: AnalysisRun, steps: list[AnalysisRunStep]) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO analysis_runs (
                    id, match_id, trigger_type, status, started_at, completed_at,
                    scheduled_for, current_step_key, note, is_reference, is_ignored,
                    metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    run.id,
                    run.match_id,
                    run.trigger_type,
                    run.status,
                    self._isoformat(run.started_at),
                    self._isoformat(run.completed_at),
                    self._isoformat(run.scheduled_for),
                    run.current_step_key,
                    run.note,
                    int(run.is_reference),
                    int(run.is_ignored),
                    dumps_json(run.metadata),
                ),
            )
            for step in steps:
                conn.execute(
                    """
                    INSERT INTO analysis_run_steps (
                        id, run_id, step_key, step_label, position, status,
                        started_at, completed_at, summary, stats_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        step.id,
                        step.run_id,
                        step.step_key,
                        step.step_label,
                        step.position,
                        step.status,
                        self._isoformat(step.started_at),
                        self._isoformat(step.completed_at),
                        step.summary,
                        dumps_json(step.stats),
                    ),
                )

    def update_analysis_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        current_step_key: str | None = None,
        completed_at: datetime | None = None,
        started_at: datetime | None = None,
        note: str | None = None,
        is_reference: bool | None = None,
        is_ignored: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        fields: list[str] = []
        params: list[Any] = []
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if current_step_key is not None:
            fields.append("current_step_key = ?")
            params.append(current_step_key)
        if completed_at is not None:
            fields.append("completed_at = ?")
            params.append(self._isoformat(completed_at))
        if started_at is not None:
            fields.append("started_at = ?")
            params.append(self._isoformat(started_at))
        if note is not None:
            fields.append("note = ?")
            params.append(note)
        if is_reference is not None:
            fields.append("is_reference = ?")
            params.append(int(is_reference))
        if is_ignored is not None:
            fields.append("is_ignored = ?")
            params.append(int(is_ignored))
        if metadata is not None:
            fields.append("metadata_json = ?")
            params.append(dumps_json(metadata))
        if not fields:
            return
        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(run_id)
        with self.database.connection() as conn:
            conn.execute(
                f"UPDATE analysis_runs SET {', '.join(fields)} WHERE id = ?",
                params,
            )

    def update_analysis_run_step(
        self,
        run_id: str,
        step_key: str,
        *,
        status: str | None = None,
        summary: str | None = None,
        stats: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        fields: list[str] = []
        params: list[Any] = []
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if summary is not None:
            fields.append("summary = ?")
            params.append(summary)
        if stats is not None:
            fields.append("stats_json = ?")
            params.append(dumps_json(stats))
        if started_at is not None:
            fields.append("started_at = ?")
            params.append(self._isoformat(started_at))
        if completed_at is not None:
            fields.append("completed_at = ?")
            params.append(self._isoformat(completed_at))
        if not fields:
            return
        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.extend([run_id, step_key])
        with self.database.connection() as conn:
            conn.execute(
                f"UPDATE analysis_run_steps SET {', '.join(fields)} WHERE run_id = ? AND step_key = ?",
                params,
            )

    def append_analysis_step_log(self, log: AnalysisStepLog) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO analysis_step_logs (id, step_id, level, message, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    log.id,
                    log.step_id,
                    log.level,
                    log.message,
                    dumps_json(log.metadata),
                    self._isoformat(log.created_at),
                ),
            )

    def save_analysis_artifact(self, artifact: AnalysisArtifact) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO analysis_artifacts (id, run_id, step_id, artifact_type, label, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.id,
                    artifact.run_id,
                    artifact.step_id,
                    artifact.artifact_type,
                    artifact.label,
                    dumps_json(artifact.payload),
                    self._isoformat(artifact.created_at),
                ),
            )

    def get_analysis_step_id(self, run_id: str, step_key: str) -> str | None:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT id FROM analysis_run_steps WHERE run_id = ? AND step_key = ?",
                (run_id, step_key),
            ).fetchone()
        return row["id"] if row else None

    def get_analysis_run_detail(self, run_id: str) -> dict[str, Any] | None:
        with self.database.connection() as conn:
            run_row = conn.execute(
                """
                SELECT ar.*,
                       m.tournament_stage,
                       ht.name AS home_team,
                       at.name AS away_team
                FROM analysis_runs ar
                JOIN matches m ON m.id = ar.match_id
                LEFT JOIN teams ht ON ht.id = m.home_team_id
                LEFT JOIN teams at ON at.id = m.away_team_id
                WHERE ar.id = ?
                """,
                (run_id,),
            ).fetchone()
            if not run_row:
                return None
            step_rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM analysis_run_steps
                    WHERE run_id = ?
                    ORDER BY position
                    """,
                    (run_id,),
                )
            ]
            log_rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT l.*, s.step_key
                    FROM analysis_step_logs l
                    JOIN analysis_run_steps s ON s.id = l.step_id
                    WHERE s.run_id = ?
                    ORDER BY l.created_at
                    """,
                    (run_id,),
                )
            ]
            artifact_rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT a.*, s.step_key
                    FROM analysis_artifacts a
                    LEFT JOIN analysis_run_steps s ON s.id = a.step_id
                    WHERE a.run_id = ?
                    ORDER BY a.created_at
                    """,
                    (run_id,),
                )
            ]

        steps_by_id = {step["id"]: step for step in step_rows}
        for step in steps_by_id.values():
            step["stats"] = self._loads_json(step.pop("stats_json", None), {})
            step["logs"] = []
            step["artifacts"] = []
        for log in log_rows:
            log["metadata"] = self._loads_json(log.pop("metadata_json", None), {})
            step = steps_by_id.get(log["step_id"])
            if step:
                step["logs"].append(log)
        for artifact in artifact_rows:
            artifact["payload"] = self._loads_json(artifact.pop("payload_json", None), {})
            if artifact.get("step_id") and artifact["step_id"] in steps_by_id:
                steps_by_id[artifact["step_id"]]["artifacts"].append(artifact)
        run_payload = dict(run_row)
        run_payload["metadata"] = self._loads_json(run_payload.pop("metadata_json", None), {})
        run_payload["steps"] = list(steps_by_id.values())
        run_payload["artifacts"] = [dict(artifact) for artifact in artifact_rows]
        return run_payload

    def list_analysis_runs(
        self,
        *,
        match_id: str | None = None,
        status: str | None = None,
        trigger_type: str | None = None,
        include_ignored: bool = True,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[Any] = []
        if match_id:
            filters.append("ar.match_id = ?")
            params.append(match_id)
        if status:
            filters.append("ar.status = ?")
            params.append(status)
        if trigger_type:
            filters.append("ar.trigger_type = ?")
            params.append(trigger_type)
        if not include_ignored:
            filters.append("ar.is_ignored = 0")
        if start_date:
            filters.append("DATE(COALESCE(ar.scheduled_for, ar.started_at)) >= DATE(?)")
            params.append(start_date)
        if end_date:
            filters.append("DATE(COALESCE(ar.scheduled_for, ar.started_at)) <= DATE(?)")
            params.append(end_date)
        query = """
            SELECT ar.*,
                   m.tournament_stage,
                   ht.name AS home_team,
                   at.name AS away_team,
                   (
                       SELECT COUNT(*)
                       FROM analysis_run_steps s
                       WHERE s.run_id = ar.id AND s.status = 'failed'
                   ) AS failed_steps,
                   (
                       SELECT COUNT(*)
                       FROM analysis_run_steps s
                       WHERE s.run_id = ar.id AND s.status = 'success'
                   ) AS successful_steps
            FROM analysis_runs ar
            JOIN matches m ON m.id = ar.match_id
            LEFT JOIN teams ht ON ht.id = m.home_team_id
            LEFT JOIN teams at ON at.id = m.away_team_id
        """
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY COALESCE(ar.scheduled_for, ar.started_at) DESC, ar.created_at DESC"
        with self.database.connection() as conn:
            rows = [dict(row) for row in conn.execute(query, params)]
        for row in rows:
            row["metadata"] = self._loads_json(row.pop("metadata_json", None), {})
        return rows

    def get_analysis_queue(self) -> list[dict[str, Any]]:
        return self.list_analysis_runs(status="queued")

    def get_analysis_health_metrics(self) -> dict[str, Any]:
        with self.database.connection() as conn:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_runs,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successful_runs,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
                    AVG(
                        CASE
                            WHEN completed_at IS NOT NULL
                            THEN ROUND((julianday(completed_at) - julianday(started_at)) * 86400, 1)
                        END
                    ) AS avg_duration_seconds
                FROM analysis_runs
                WHERE is_ignored = 0
                """
            ).fetchone()
            step_success = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT step_key,
                           COUNT(*) AS total,
                           SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successful
                    FROM analysis_run_steps
                    GROUP BY step_key
                    ORDER BY MIN(position)
                    """
                )
            ]
            transcript_statuses = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM transcripts
                    GROUP BY status
                    ORDER BY count DESC
                    """
                )
            ]
            timeline = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT DATE(COALESCE(completed_at, started_at)) AS day,
                           COUNT(*) AS runs,
                           SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successes
                    FROM analysis_runs
                    WHERE DATE(COALESCE(completed_at, started_at)) IS NOT NULL
                    GROUP BY DATE(COALESCE(completed_at, started_at))
                    ORDER BY day
                    """
                )
            ]
        unavailable_count = next((row["count"] for row in transcript_statuses if row["status"] == "unavailable"), 0)
        total_transcripts = sum(row["count"] for row in transcript_statuses)
        return {
            "total_runs": totals["total_runs"] or 0,
            "successful_runs": totals["successful_runs"] or 0,
            "failed_runs": totals["failed_runs"] or 0,
            "avg_duration_seconds": round(totals["avg_duration_seconds"] or 0, 1),
            "step_success": [
                {
                    **row,
                    "success_rate": round(((row["successful"] or 0) / row["total"]) * 100, 1) if row["total"] else 0.0,
                }
                for row in step_success
            ],
            "transcript_unavailable_rate": round((unavailable_count / total_transcripts) * 100, 1) if total_transcripts else 0.0,
            "timeline": timeline,
        }

    def compare_analysis_runs(self, baseline_run_id: str, candidate_run_id: str) -> dict[str, Any]:
        baseline = self.get_analysis_run_detail(baseline_run_id)
        candidate = self.get_analysis_run_detail(candidate_run_id)
        if not baseline or not candidate:
            return {"baseline": baseline, "candidate": candidate, "changes": []}

        def _index_artifacts(run_payload: dict[str, Any], artifact_type: str) -> dict[str, dict[str, Any]]:
            payload: dict[str, dict[str, Any]] = {}
            for artifact in run_payload.get("artifacts", []):
                if artifact["artifact_type"] != artifact_type:
                    continue
                items = artifact["payload"].get("items", [])
                for item in items:
                    payload[item.get("key") or item.get("video_id") or item.get("value") or artifact["label"]] = item
            return payload

        baseline_predictions = _index_artifacts(baseline, "predictions")
        candidate_predictions = _index_artifacts(candidate, "predictions")
        all_keys = sorted(set(baseline_predictions) | set(candidate_predictions))
        changes = []
        for key in all_keys:
            before = baseline_predictions.get(key)
            after = candidate_predictions.get(key)
            if before == after:
                continue
            changes.append({"key": key, "before": before, "after": after})
        return {"baseline": baseline, "candidate": candidate, "changes": changes}

    def update_analysis_run_annotation(
        self,
        run_id: str,
        *,
        note: str | None,
        is_reference: bool,
        is_ignored: bool,
    ) -> None:
        self.update_analysis_run(
            run_id,
            note=note or "",
            is_reference=is_reference,
            is_ignored=is_ignored,
        )

    def has_matches(self) -> bool:
        with self.database.connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] > 0
