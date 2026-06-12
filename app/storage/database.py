from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS creators (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        language TEXT NOT NULL,
        historical_accuracy REAL NOT NULL DEFAULT 0.5,
        weight REAL NOT NULL DEFAULT 1.0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS channels (
        id TEXT PRIMARY KEY,
        creator_id TEXT NOT NULL REFERENCES creators(id),
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        language TEXT NOT NULL,
        region TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        keywords_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS teams (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        code TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS matches (
        id TEXT PRIMARY KEY,
        tournament_stage TEXT NOT NULL,
        home_team_id TEXT REFERENCES teams(id),
        away_team_id TEXT REFERENCES teams(id),
        scheduled_at TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS videos (
        id TEXT PRIMARY KEY,
        channel_id TEXT NOT NULL REFERENCES channels(id),
        creator_id TEXT NOT NULL REFERENCES creators(id),
        video_id TEXT NOT NULL UNIQUE,
        video_url TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        publish_date TEXT NOT NULL,
        language TEXT NOT NULL,
        duration_seconds INTEGER,
        is_world_cup_related INTEGER NOT NULL DEFAULT 1,
        source_payload_json TEXT NOT NULL DEFAULT '{}',
        reprocess_version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transcripts (
        id TEXT PRIMARY KEY,
        video_id TEXT NOT NULL REFERENCES videos(id),
        status TEXT NOT NULL,
        text TEXT,
        language TEXT,
        segments_json TEXT NOT NULL DEFAULT '[]',
        version INTEGER NOT NULL DEFAULT 1,
        source TEXT NOT NULL DEFAULT 'demo',
        extracted_at TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS predictions (
        id TEXT PRIMARY KEY,
        video_id TEXT NOT NULL REFERENCES videos(id),
        transcript_id TEXT REFERENCES transcripts(id),
        extractor_version TEXT NOT NULL,
        language TEXT NOT NULL,
        summary TEXT NOT NULL,
        confidence REAL NOT NULL,
        raw_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS prediction_items (
        id TEXT PRIMARY KEY,
        prediction_id TEXT NOT NULL REFERENCES predictions(id),
        item_type TEXT NOT NULL,
        subject TEXT,
        value TEXT NOT NULL,
        confidence REAL NOT NULL,
        rationale TEXT,
        quote TEXT,
        match_id TEXT REFERENCES matches(id),
        team_id TEXT REFERENCES teams(id),
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_videos_language ON videos(language)",
    "CREATE INDEX IF NOT EXISTS idx_videos_publish_date ON videos(publish_date)",
    "CREATE INDEX IF NOT EXISTS idx_videos_channel_id ON videos(channel_id)",
    "CREATE INDEX IF NOT EXISTS idx_transcripts_video_id ON transcripts(video_id)",
    "CREATE INDEX IF NOT EXISTS idx_predictions_video_id ON predictions(video_id)",
    "CREATE INDEX IF NOT EXISTS idx_prediction_items_type ON prediction_items(item_type)",
    "CREATE INDEX IF NOT EXISTS idx_prediction_items_match_id ON prediction_items(match_id)",
    "CREATE INDEX IF NOT EXISTS idx_prediction_items_team_id ON prediction_items(team_id)",
]


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)


def dumps_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)
