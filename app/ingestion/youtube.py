from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

from app.config import ChannelConfig, Settings
from app.models.entities import Channel, Creator, Video
from app.utils.text import build_world_cup_search_query, contains_keywords, has_negated_world_cup_context

logger = logging.getLogger(__name__)
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
YOUTUBE_DURATION_PATTERN = re.compile(
    r"^PT(?=(?:\d+H|\d+M|\d+S))(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)


class DemoYouTubeSource:
    def __init__(self, demo_data_path: Path) -> None:
        self.demo_data_path = demo_data_path

    def load_recent_videos(self) -> list[dict[str, Any]]:
        with self.demo_data_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload.get("videos", [])

    def get_recent_videos_for_channel(self, channel: ChannelConfig) -> list[dict[str, Any]]:
        return [item for item in self.load_recent_videos() if item.get("channel_id") == channel.id]


class YouTubeApiError(RuntimeError):
    pass


class RealYouTubeSource:
    def __init__(self, api_key: str, *, max_results: int = 10, timeout: int = 15) -> None:
        self.api_key = api_key
        self.max_results = max_results
        self.timeout = timeout

    def _fetch_json(self, resource: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urlencode({"key": self.api_key, **params})
        url = f"{YOUTUBE_API_BASE_URL}/{resource}?{query}"
        try:
            with urlopen(url, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise YouTubeApiError(f"YouTube API request failed for {resource}: {exc.code} {detail}") from exc
        except URLError as exc:
            raise YouTubeApiError(f"YouTube API request failed for {resource}: {exc.reason}") from exc

    def resolve_channel_id(self, channel: ChannelConfig) -> str:
        if channel.youtube_channel_id:
            return channel.youtube_channel_id
        if direct_channel_id := extract_youtube_channel_id(channel.url):
            return direct_channel_id
        if not (handle := extract_youtube_handle(channel.url)):
            raise YouTubeApiError(f"Cannot resolve a YouTube channel from URL: {channel.url}")
        payload = self._fetch_json("channels", {"part": "id", "forHandle": handle})
        items = payload.get("items", [])
        if not items:
            raise YouTubeApiError(f"No YouTube channel found for handle @{handle}")
        return items[0]["id"]

    def get_recent_videos_for_channel(self, channel: ChannelConfig) -> list[dict[str, Any]]:
        channel_id = self.resolve_channel_id(channel)
        search_payload = self._fetch_json(
            "search",
            {
                "part": "snippet",
                "channelId": channel_id,
                "order": "date",
                "q": build_world_cup_search_query(channel.language),
                "type": "video",
                "maxResults": self.max_results,
            },
        )
        video_ids = [
            item.get("id", {}).get("videoId")
            for item in search_payload.get("items", [])
            if item.get("id", {}).get("videoId")
        ]
        if not video_ids:
            return []
        details_payload = self._fetch_json("videos", {"part": "snippet,contentDetails", "id": ",".join(video_ids)})
        details_by_id = {item["id"]: item for item in details_payload.get("items", []) if item.get("id")}
        return [
            map_youtube_video(details_by_id[video_id], channel, channel_id)
            for video_id in video_ids
            if video_id in details_by_id
        ]


class FallbackYouTubeSource:
    def __init__(self, primary: RealYouTubeSource, fallback: DemoYouTubeSource) -> None:
        self.primary = primary
        self.fallback = fallback

    def get_recent_videos_for_channel(self, channel: ChannelConfig) -> list[dict[str, Any]]:
        try:
            return self.primary.get_recent_videos_for_channel(channel)
        except YouTubeApiError as exc:
            logger.warning("Falling back to demo YouTube ingestion for %s: %s", channel.id, exc)
            return self.fallback.get_recent_videos_for_channel(channel)


def build_youtube_source(settings: Settings) -> DemoYouTubeSource | FallbackYouTubeSource:
    demo_source = DemoYouTubeSource(settings.demo_data_path)
    if not settings.youtube_api_key:
        return demo_source
    return FallbackYouTubeSource(
        RealYouTubeSource(settings.youtube_api_key, max_results=settings.youtube_max_results),
        demo_source,
    )


def extract_youtube_channel_id(channel_url: str) -> str | None:
    path_parts = [part for part in urlparse(channel_url).path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] == "channel":
        return path_parts[1]
    return None


def extract_youtube_handle(channel_url: str) -> str | None:
    path_parts = [part for part in urlparse(channel_url).path.split("/") if part]
    if not path_parts:
        return None
    if path_parts[0].startswith("@"):
        return path_parts[0].removeprefix("@")
    if path_parts[0] in {"c", "user"} and len(path_parts) >= 2:
        return path_parts[1]
    return None


def parse_iso8601_duration(value: str | None) -> int | None:
    if not value:
        return None
    match = YOUTUBE_DURATION_PATTERN.fullmatch(value)
    if not match:
        return None
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return hours * 3600 + minutes * 60 + seconds


def map_youtube_video(video_payload: dict[str, Any], channel: ChannelConfig, youtube_channel_id: str) -> dict[str, Any]:
    snippet = video_payload.get("snippet", {})
    content_details = video_payload.get("contentDetails", {})
    video_id = video_payload["id"]
    return {
        "channel_id": channel.id,
        "youtube_channel_id": youtube_channel_id,
        "video_id": video_id,
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "publish_date": snippet.get("publishedAt"),
        "language": channel.language,
        "duration_seconds": parse_iso8601_duration(content_details.get("duration")),
        "tags": snippet.get("tags", []),
        "source_payload": video_payload,
    }


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
    title_and_tags = " ".join([video_payload.get("title", ""), " ".join(video_payload.get("tags", []))])
    if contains_keywords(title_and_tags, channel_config.language, channel_config.keywords):
        return True

    description = video_payload.get("description", "")
    if has_negated_world_cup_context(description, channel_config.language):
        return False
    return contains_keywords(description, channel_config.language, channel_config.keywords)


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
