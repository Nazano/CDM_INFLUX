from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.models.entities import Transcript, TranscriptSegment

logger = logging.getLogger(__name__)


# TODO: integrate a real transcript provider (YouTube captions API / scraping / third-party provider).
def extract_transcript(
    video_id: str,
    transcript_hint: str | None = None,
    language: str | None = None,
    transcript_segments: list[dict[str, Any]] | None = None,
) -> Transcript:
    if transcript_hint:
        segments = [
            TranscriptSegment.model_validate(segment)
            for segment in (transcript_segments or _simulate_segments(transcript_hint))
        ]
        return Transcript(
            id=f"transcript-{video_id}",
            video_id=video_id,
            status="available",
            text=transcript_hint,
            language=language,
            segments=segments,
            extracted_at=datetime.now(UTC),
        )

    simulated_text = (
        "Transcript unavailable from source. Simulated analysis placeholder for World Cup 2026 discussion."
    )
    return Transcript(
        id=f"transcript-{video_id}",
        video_id=video_id,
        status="simulated",
        text=simulated_text,
        language=language,
        segments=_simulate_segments(simulated_text),
        extracted_at=datetime.now(UTC),
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
