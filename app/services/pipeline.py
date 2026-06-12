from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.config import AppConfig, Settings, get_settings, load_app_config
from app.extraction.predictions import extract_predictions
from app.extraction.transcripts import extract_transcript
from app.ingestion.youtube import build_channel, build_creator, build_video, build_youtube_source, is_world_cup_video
from app.models.entities import Prediction
from app.storage.database import Database
from app.storage.repositories import Repository

logger = logging.getLogger(__name__)


class DemoPipeline:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.database = Database(self.settings.db_path)
        self.repository = Repository(self.database)
        self.source = build_youtube_source(self.settings)

    def initialize(self) -> None:
        self.database.initialize()

    def load_demo_payload(self) -> dict[str, Any]:
        with self.settings.demo_data_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def run(self, config: AppConfig | None = None) -> dict[str, int]:
        config = config or load_app_config(self.settings.config_path)
        self.initialize()
        ingested_videos = 0
        extracted_predictions = 0
        demo_payload = self.load_demo_payload()
        transcript_map = {item["video_id"]: item for item in demo_payload.get("videos", [])}

        for channel_config in config.channels:
            creator = build_creator(channel_config)
            channel = build_channel(channel_config)
            self.repository.upsert_creator(creator)
            self.repository.upsert_channel(channel)

            for video_payload in self.source.get_recent_videos_for_channel(channel_config):
                if not is_world_cup_video(video_payload, channel_config):
                    continue
                video = build_video(video_payload, channel)
                self.repository.upsert_video(video)
                ingested_videos += 1

                transcript_source = transcript_map.get(video.video_id, {})
                transcript = extract_transcript(
                    video.video_id,
                    transcript_hint=transcript_source.get("transcript_text"),
                    language=video.language,
                    transcript_segments=transcript_source.get("transcript_segments"),
                )
                transcript.video_id = video.id
                transcript.id = f"transcript-{video.video_id}"
                self.repository.save_transcript(transcript)

                extracted = extract_predictions(transcript.text or "")
                prediction = Prediction(
                    id=f"prediction-{uuid.uuid4().hex[:12]}",
                    video_id=video.id,
                    transcript_id=transcript.id,
                    extractor_version="rules-v1",
                    language=video.language,
                    summary=extracted.summary,
                    confidence=extracted.confidence,
                    raw_json=extracted.model_dump(mode="json"),
                )
                for item in extracted.items:
                    item.prediction_id = prediction.id
                self.repository.save_prediction(prediction, extracted)
                extracted_predictions += len(extracted.items)

        return {"videos": ingested_videos, "prediction_items": extracted_predictions}


def bootstrap_demo_environment() -> Repository:
    pipeline = DemoPipeline()
    pipeline.initialize()
    if pipeline.repository.is_empty():
        pipeline.run()
    return pipeline.repository
