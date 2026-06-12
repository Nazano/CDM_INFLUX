from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import ChannelConfig
from app.models.entities import Channel, Creator, Video
from app.utils.text import contains_keywords

logger = logging.getLogger(__name__)


class DemoYouTubeSource:
    def __init__(self, demo_data_path: Path) -> None:
        self.demo_data_path = demo_data_path

    def load_recent_videos(self) -> list[dict[str, Any]]:
        with self.demo_data_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload.get("videos", [])

    # TODO: replace this demo source with a real YouTube Data API integration.
    def get_recent_videos_for_channel(self, channel: ChannelConfig) -> list[dict[str, Any]]:
        return [item for item in self.load_recent_videos() if item.get("channel_id") == channel.id]


def build_creator(channel_config: ChannelConfig) -> Creator:
    return Creator(
        id=f"creator-{channel_config.id}",
        name=channel_config.name,
        language=channel_config.language,
    )


def build_channel(channel_config: ChannelConfig) -> Channel:
    creator = build_creator(channel_config)
    return Channel(
        id=channel_config.id,
        creator_id=creator.id,
        name=channel_config.name,
        url=channel_config.url,
        language=channel_config.language,
        region=channel_config.region,
        active=channel_config.active,
        keywords=channel_config.keywords,
    )


def is_world_cup_video(video_payload: dict[str, Any], channel_config: ChannelConfig) -> bool:
    combined = " ".join(
        [
            video_payload.get("title", ""),
            video_payload.get("description", ""),
            " ".join(video_payload.get("tags", [])),
        ]
    )
    return contains_keywords(combined, channel_config.language, channel_config.keywords)


def build_video(video_payload: dict[str, Any], channel: Channel) -> Video:
    return Video(
        id=f"video-{video_payload['video_id']}",
        channel_id=channel.id,
        creator_id=channel.creator_id,
        video_id=video_payload["video_id"],
        video_url=video_payload["video_url"],
        title=video_payload["title"],
        description=video_payload.get("description", ""),
        publish_date=video_payload["publish_date"],
        language=video_payload.get("language", channel.language),
        duration_seconds=video_payload.get("duration_seconds"),
        is_world_cup_related=bool(video_payload.get("is_world_cup_related", True)),
        source_payload=video_payload,
    )
