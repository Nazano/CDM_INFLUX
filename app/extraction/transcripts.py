from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html import unescape
from math import ceil, floor
from datetime import UTC, datetime
from typing import Any, Callable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import Settings, get_settings
from app.models.entities import Transcript, TranscriptSegment
from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, VideoUnavailable, YouTubeTranscriptApi, YouTubeTranscriptApiException

logger = logging.getLogger(__name__)
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
_WEBVTT_TIMESTAMP_PATTERN = re.compile(
    r"^(?:(?P<hours>\d+):)?(?P<minutes>\d{2}):(?P<seconds>\d{2})\.(?P<millis>\d{3})$"
)
_WEBVTT_TAG_PATTERN = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class TranscriptRequest:
    video_id: str
    transcript_hint: str | None = None
    language: str | None = None
    transcript_segments: list[dict[str, Any]] | None = None


class YouTubeCaptionApiError(RuntimeError):
    pass


def extract_transcript(
    video_id: str,
    transcript_hint: str | None = None,
    language: str | None = None,
    transcript_segments: list[dict[str, Any]] | None = None,
    *,
    enabled: bool = True,
    settings: Settings | None = None,
) -> Transcript:
    request = TranscriptRequest(
        video_id=video_id,
        transcript_hint=transcript_hint,
        language=language,
        transcript_segments=transcript_segments,
    )
    return extract_transcripts([request], enabled=enabled, settings=settings)[0]


def extract_transcripts(
    requests: Sequence[TranscriptRequest],
    *,
    enabled: bool = True,
    settings: Settings | None = None,
    fallback_delay_seconds: int | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[Transcript]:
    if not requests:
        return []

    current_settings = settings or get_settings()
    transcripts_by_video_id: dict[str, Transcript] = {}
    live_requests: list[TranscriptRequest] = []

    for request in requests:
        if request.transcript_hint:
            segments = _coerce_segments(request.transcript_segments or _simulate_segments(request.transcript_hint))
            transcripts_by_video_id[request.video_id] = _build_transcript(
                request.video_id,
                status="available",
                text=request.transcript_hint,
                language=request.language,
                segments=segments,
                source="demo",
            )
            continue
        if not enabled:
            logger.debug("Live transcript fetch disabled for %s", request.video_id)
            transcripts_by_video_id[request.video_id] = _build_transcript(
                request.video_id,
                status="unavailable",
                text=None,
                language=request.language,
                segments=[],
                source="transcripts_disabled",
            )
            continue
        live_requests.append(request)

    if live_requests:
        caption_results, fallback_requests = _fetch_captions_batch(live_requests, current_settings)
        transcripts_by_video_id.update(caption_results)
        transcripts_by_video_id.update(
            _fetch_fallback_queue(
                fallback_requests,
                delay_seconds=(
                    current_settings.youtube_transcript_fallback_delay_seconds
                    if fallback_delay_seconds is None
                    else fallback_delay_seconds
                ),
                sleep_fn=sleep_fn,
            )
        )

    return [transcripts_by_video_id[request.video_id] for request in requests]


def _simulate_segments(text: str) -> list[TranscriptSegment]:
    parts = [segment.strip() for segment in text.split(".") if segment.strip()]
    segments: list[TranscriptSegment] = []
    cursor = 0
    for index, part in enumerate(parts, start=1):
        duration = max(8, min(24, len(part) // 6 + 4))
        segments.append(
            TranscriptSegment(
                start_seconds=cursor,
                end_seconds=cursor + duration,
                text=part,
            )
        )
        cursor += duration
    if not segments:
        segments.append(TranscriptSegment(start_seconds=0, end_seconds=10, text=text))
    return segments


def _fetch_captions_batch(
    requests: Sequence[TranscriptRequest],
    settings: Settings,
) -> tuple[dict[str, Transcript], list[TranscriptRequest]]:
    if not requests:
        return {}, []
    if not (settings.youtube_api_key or settings.youtube_captions_oauth_token):
        return {}, list(requests)

    batch_size = max(1, settings.youtube_caption_batch_size)
    results: dict[str, Transcript] = {}
    fallback_requests: list[TranscriptRequest] = []

    for index in range(0, len(requests), batch_size):
        chunk = list(requests[index:index + batch_size])
        with ThreadPoolExecutor(max_workers=min(batch_size, len(chunk))) as executor:
            ordered_results = list(executor.map(lambda req: _try_fetch_caption_transcript(req, settings), chunk))
        for request, transcript in zip(chunk, ordered_results):
            if transcript is None:
                fallback_requests.append(request)
            else:
                results[request.video_id] = transcript
    return results, fallback_requests


def _try_fetch_caption_transcript(request: TranscriptRequest, settings: Settings) -> Transcript | None:
    try:
        tracks = _list_caption_tracks(request.video_id, settings)
        track = _select_caption_track(tracks, request.language)
        if not track:
            return None
        payload = _download_caption_track(track["id"], settings)
        segments = _parse_webvtt_segments(payload)
        if not segments:
            return None
        return _build_transcript(
            request.video_id,
            status="available",
            text=" ".join(segment.text for segment in segments).strip() or None,
            language=(track.get("snippet") or {}).get("language") or request.language,
            segments=segments,
            source=_caption_track_source(track),
        )
    except YouTubeCaptionApiError as exc:
        logger.warning("Caption API retrieval failed for %s: %s", request.video_id, exc)
        return None


def _fetch_fallback_queue(
    requests: Sequence[TranscriptRequest],
    *,
    delay_seconds: int,
    sleep_fn: Callable[[float], None],
) -> dict[str, Transcript]:
    results: dict[str, Transcript] = {}
    for index, request in enumerate(requests):
        if index and delay_seconds > 0:
            sleep_fn(delay_seconds)
        try:
            fetched = _fetch_youtube_transcript(request.video_id, request.language)
        except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable) as exc:
            logger.warning("Transcript unavailable for %s: %s", request.video_id, exc)
            results[request.video_id] = _build_transcript(
                request.video_id,
                status="unavailable",
                text=None,
                language=request.language,
                segments=[],
                source="youtube_transcript_api",
            )
            continue
        except YouTubeTranscriptApiException as exc:
            logger.warning("Transcript retrieval failed for %s: %s", request.video_id, exc)
            results[request.video_id] = _build_transcript(
                request.video_id,
                status="error",
                text=None,
                language=request.language,
                segments=[],
                source="youtube_transcript_api",
            )
            continue

        text = " ".join(segment.text for segment in fetched["segments"]).strip() or None
        results[request.video_id] = _build_transcript(
            request.video_id,
            status="available",
            text=text,
            language=fetched["language"],
            segments=fetched["segments"],
            source=fetched["source"],
        )
    return results


def _fetch_youtube_transcript(video_id: str, language: str | None) -> dict[str, Any]:
    transcript = _build_youtube_transcript_client().list(video_id).find_transcript(_language_preferences(language)).fetch()
    segments = [
        TranscriptSegment(
            start_seconds=(start_seconds := max(0, floor(snippet.start))),
            end_seconds=max(start_seconds + 1, ceil(snippet.start + snippet.duration)),
            text=snippet.text.strip(),
        )
        for snippet in transcript
        if snippet.text.strip()
    ]
    return {
        "language": transcript.language_code or language,
        "segments": segments,
        "source": "youtube_transcript_api_generated" if transcript.is_generated else "youtube_transcript_api",
    }


def _build_youtube_transcript_client() -> YouTubeTranscriptApi:
    return YouTubeTranscriptApi()


def _coerce_segments(segments: list[dict[str, Any]] | list[TranscriptSegment]) -> list[TranscriptSegment]:
    return [segment if isinstance(segment, TranscriptSegment) else TranscriptSegment.model_validate(segment) for segment in segments]


def _language_preferences(language: str | None) -> list[str]:
    preferences = {
        "en": ["en", "en-US", "en-GB"],
        "fr": ["fr", "fr-FR", "en"],
        "es": ["es", "es-ES", "es-419", "en"],
    }
    if language and language in preferences:
        return preferences[language]
    if language:
        return [language, "en"]
    return ["en", "en-US", "en-GB"]


def _build_transcript(
    video_id: str,
    *,
    status: str,
    text: str | None,
    language: str | None,
    segments: list[TranscriptSegment],
    source: str,
) -> Transcript:
    return Transcript(
        id=f"transcript-{video_id}",
        video_id=video_id,
        status=status,
        text=text,
        language=language,
        segments=segments,
        extracted_at=datetime.now(UTC),
        source=source,
    )


def _list_caption_tracks(video_id: str, settings: Settings) -> list[dict[str, Any]]:
    payload = _fetch_caption_api_json(
        "captions",
        {"part": "snippet", "videoId": video_id},
        settings,
    )
    return [item for item in payload.get("items", []) if isinstance(item, dict)]


def _download_caption_track(caption_id: str, settings: Settings) -> str:
    return _fetch_caption_api_text(
        f"captions/{caption_id}",
        {"alt": "media", "tfmt": "vtt"},
        settings,
    )


def _fetch_caption_api_json(resource: str, params: dict[str, Any], settings: Settings) -> dict[str, Any]:
    raw = _fetch_caption_api_response(resource, params, settings)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise YouTubeCaptionApiError(f"Invalid JSON payload for {resource}") from exc


def _fetch_caption_api_text(resource: str, params: dict[str, Any], settings: Settings) -> str:
    return _fetch_caption_api_response(resource, params, settings)


def _fetch_caption_api_response(resource: str, params: dict[str, Any], settings: Settings) -> str:
    query_params = dict(params)
    if settings.youtube_api_key:
        query_params["key"] = settings.youtube_api_key
    query = urlencode(query_params)
    url = f"{YOUTUBE_API_BASE_URL}/{resource}?{query}"
    headers = {"Accept": "application/json"}
    if settings.youtube_captions_oauth_token:
        headers["Authorization"] = "Bearer " + settings.youtube_captions_oauth_token
    if query_params.get("alt") == "media":
        headers["Accept"] = "text/vtt"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="ignore")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise YouTubeCaptionApiError(f"{resource} failed: {exc.code} {detail}") from exc
    except URLError as exc:
        raise YouTubeCaptionApiError(f"{resource} failed: {exc.reason}") from exc


def _select_caption_track(items: Sequence[dict[str, Any]], language: str | None) -> dict[str, Any] | None:
    candidates = [item for item in items if (item.get("snippet") or {}).get("status") == "serving"]
    if not candidates:
        return None

    preferences = _language_preferences(language)

    def score(item: dict[str, Any]) -> tuple[int, int]:
        snippet = item.get("snippet") or {}
        track_language = str(snippet.get("language") or "")
        primary_language = track_language.split("-", 1)[0]
        try:
            language_score = preferences.index(track_language)
        except ValueError:
            try:
                language_score = preferences.index(primary_language)
            except ValueError:
                language_score = len(preferences) + 1
        track_kind = str(snippet.get("trackKind") or "standard").upper()
        kind_score = 1 if track_kind == "ASR" else 0
        return language_score, kind_score

    return min(candidates, key=score)


def _caption_track_source(track: dict[str, Any]) -> str:
    track_kind = str((track.get("snippet") or {}).get("trackKind") or "standard").upper()
    return "youtube_caption_api_generated" if track_kind == "ASR" else "youtube_caption_api"


def _parse_webvtt_segments(payload: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    current_start: int | None = None
    current_end: int | None = None
    text_lines: list[str] = []

    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line or line == "WEBVTT" or line.startswith("NOTE") or line.startswith("STYLE"):
            if current_start is not None and text_lines:
                text = _clean_caption_text(" ".join(text_lines))
                if text:
                    segments.append(
                        TranscriptSegment(
                            start_seconds=current_start,
                            end_seconds=max(current_start + 1, current_end or current_start + 1),
                            text=text,
                        )
                    )
            current_start = None
            current_end = None
            text_lines = []
            continue
        if line.isdigit():
            continue
        if "-->" in line:
            start_raw, end_raw = [part.strip().split(" ", 1)[0] for part in line.split("-->", 1)]
            current_start = _parse_webvtt_timestamp(start_raw)
            current_end = _parse_webvtt_timestamp(end_raw)
            text_lines = []
            continue
        if current_start is not None:
            text_lines.append(line)

    if current_start is not None and text_lines:
        text = _clean_caption_text(" ".join(text_lines))
        if text:
            segments.append(
                TranscriptSegment(
                    start_seconds=current_start,
                    end_seconds=max(current_start + 1, current_end or current_start + 1),
                    text=text,
                )
            )

    return segments


def _parse_webvtt_timestamp(value: str) -> int:
    match = _WEBVTT_TIMESTAMP_PATTERN.match(value)
    if not match:
        return 0
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    millis = int(match.group("millis") or 0)
    total = hours * 3600 + minutes * 60 + seconds + (millis / 1000)
    return max(0, floor(total))


def _clean_caption_text(value: str) -> str:
    return unescape(_WEBVTT_TAG_PATTERN.sub("", value)).strip()
