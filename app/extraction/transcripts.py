from __future__ import annotations

import logging
from math import ceil, floor
from datetime import UTC, datetime
from typing import Any

from app.models.entities import Transcript, TranscriptSegment
from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, VideoUnavailable, YouTubeTranscriptApi, YouTubeTranscriptApiException

logger = logging.getLogger(__name__)


def extract_transcript(
    video_id: str,
    transcript_hint: str | None = None,
    language: str | None = None,
    transcript_segments: list[dict[str, Any]] | None = None,
) -> Transcript:
    if transcript_hint:
        segments = _coerce_segments(transcript_segments or _simulate_segments(transcript_hint))
        return Transcript(
            id=f"transcript-{video_id}",
            video_id=video_id,
            status="available",
            text=transcript_hint,
            language=language,
            segments=segments,
            extracted_at=datetime.now(UTC),
            source="demo",
        )

    try:
        fetched = _fetch_youtube_transcript(video_id, language)
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable) as exc:
        logger.warning("Transcript unavailable for %s: %s", video_id, exc)
        return Transcript(
            id=f"transcript-{video_id}",
            video_id=video_id,
            status="unavailable",
            text=None,
            language=language,
            segments=[],
            extracted_at=datetime.now(UTC),
            source="youtube",
        )
    except YouTubeTranscriptApiException as exc:
        logger.warning("Transcript retrieval failed for %s: %s", video_id, exc)
        return Transcript(
            id=f"transcript-{video_id}",
            video_id=video_id,
            status="error",
            text=None,
            language=language,
            segments=[],
            extracted_at=datetime.now(UTC),
            source="youtube",
        )

    text = " ".join(segment.text for segment in fetched["segments"]).strip() or None
    return Transcript(
        id=f"transcript-{video_id}",
        video_id=video_id,
        status="available",
        text=text,
        language=fetched["language"],
        segments=fetched["segments"],
        extracted_at=datetime.now(UTC),
        source=fetched["source"],
    )


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


def _fetch_youtube_transcript(video_id: str, language: str | None) -> dict[str, Any]:
    transcript = _build_youtube_transcript_client().list(video_id).find_transcript(_language_preferences(language)).fetch()
    segments = [
        TranscriptSegment(
            start_seconds=max(0, floor(snippet.start)),
            end_seconds=max(max(0, floor(snippet.start)) + 1, ceil(snippet.start + snippet.duration)),
            text=snippet.text.strip(),
        )
        for snippet in transcript
        if snippet.text.strip()
    ]
    return {
        "language": transcript.language_code or language,
        "segments": segments,
        "source": "youtube_generated" if transcript.is_generated else "youtube",
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
