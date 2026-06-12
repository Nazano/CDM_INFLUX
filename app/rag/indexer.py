from __future__ import annotations

from app.rag.chroma_store import ChromaStore
from app.storage.repositories import Repository


def index_transcript_for_video(
    video_id: str,
    repository: Repository,
    chroma_store: ChromaStore,
    metadata: dict[str, str | None] | None = None,
) -> dict[str, int]:
    detail = repository.get_video_detail(video_id)
    if not detail:
        return {"indexed_videos": 0, "indexed_chunks": 0, "skipped_videos": 1}

    transcript = detail.get("transcript") or {}
    transcript_status = transcript.get("status")
    transcript_text = (transcript.get("text") or "").strip()
    if transcript_status != "available" or not transcript_text:
        return {"indexed_videos": 0, "indexed_chunks": 0, "skipped_videos": 1}

    raw_video = detail.get("video") or {}
    source_video_id = raw_video.get("video_id") or video_id
    if chroma_store.is_indexed(source_video_id):
        return {"indexed_videos": 0, "indexed_chunks": 0, "skipped_videos": 1}

    indexed_chunks = chroma_store.index_transcript(
        transcript.get("id") or f"transcript-{source_video_id}",
        source_video_id,
        transcript_text,
        metadata={
            "video_db_id": raw_video.get("id"),
            "video_title": raw_video.get("title"),
            "language": transcript.get("language") or raw_video.get("language"),
            **(metadata or {}),
        },
    )
    if indexed_chunks <= 0:
        return {"indexed_videos": 0, "indexed_chunks": 0, "skipped_videos": 1}
    return {"indexed_videos": 1, "indexed_chunks": indexed_chunks, "skipped_videos": 0}


def index_all_transcripts(repository: Repository, chroma_store: ChromaStore) -> dict[str, int]:
    transcripts = repository.list_available_transcripts()
    summary = {"available_transcripts": len(transcripts), "indexed_videos": 0, "indexed_chunks": 0, "skipped_videos": 0}
    for transcript in transcripts:
        source_video_id = transcript.get("video_id")
        transcript_text = (transcript.get("text") or "").strip()
        if not source_video_id or not transcript_text or chroma_store.is_indexed(source_video_id):
            summary["skipped_videos"] += 1
            continue
        indexed_chunks = chroma_store.index_transcript(
            transcript.get("id") or f"transcript-{source_video_id}",
            source_video_id,
            transcript_text,
            metadata={
                "video_db_id": transcript.get("video_db_id"),
                "video_title": transcript.get("video_title"),
                "language": transcript.get("language"),
                "source": transcript.get("source"),
            },
        )
        if indexed_chunks <= 0:
            summary["skipped_videos"] += 1
            continue
        summary["indexed_videos"] += 1
        summary["indexed_chunks"] += indexed_chunks
    return summary
