from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


PredictionItemType = Literal[
    "tournament_winner",
    "match_winner",
    "exact_score",
    "qualified_team",
    "group_ranking",
    "argument",
    "confidence_signal",
]
TranscriptStatus = Literal["available", "unavailable", "simulated", "error"]


class Creator(BaseModel):
    id: str
    name: str
    language: str
    historical_accuracy: float = 0.5
    weight: float = 1.0


class Channel(BaseModel):
    id: str
    creator_id: str
    name: str
    url: str
    language: str
    region: str | None = None
    active: bool = True
    keywords: list[str] = Field(default_factory=list)


class Team(BaseModel):
    id: str
    name: str
    code: str | None = None


class Match(BaseModel):
    id: str
    tournament_stage: str
    home_team_id: str | None = None
    away_team_id: str | None = None
    scheduled_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Video(BaseModel):
    id: str
    channel_id: str
    creator_id: str
    video_id: str
    video_url: str
    title: str
    description: str
    publish_date: datetime
    language: str
    duration_seconds: int | None = None
    is_world_cup_related: bool = True
    source_payload: dict[str, Any] = Field(default_factory=dict)


class TranscriptSegment(BaseModel):
    start_seconds: int
    end_seconds: int
    text: str


class Transcript(BaseModel):
    id: str
    video_id: str
    status: TranscriptStatus
    text: str | None = None
    language: str | None = None
    segments: list[TranscriptSegment] = Field(default_factory=list)
    version: int = 1
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = "demo"


class PredictionItem(BaseModel):
    id: str
    prediction_id: str
    item_type: PredictionItemType
    subject: str | None = None
    value: str
    confidence: float = 0.5
    rationale: str | None = None
    quote: str | None = None
    match_id: str | None = None
    team_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Prediction(BaseModel):
    id: str
    video_id: str
    transcript_id: str | None = None
    extractor_version: str = "rules-v1"
    language: str
    summary: str
    confidence: float = 0.5
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_json: dict[str, Any] = Field(default_factory=dict)


class ExtractedPredictions(BaseModel):
    summary: str
    confidence: float
    items: list[PredictionItem] = Field(default_factory=list)
    key_quotes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
