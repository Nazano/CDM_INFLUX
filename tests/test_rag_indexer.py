from __future__ import annotations

from app.rag.indexer import index_all_transcripts


class FakeRepository:
    def list_available_transcripts(self) -> list[dict]:
        return [
            {
                "id": "transcript-1",
                "video_db_id": "db-1",
                "video_id": "vid-1",
                "video_title": "Video 1",
                "text": "France gagne demain",
                "language": "fr",
                "source": "youtube",
            },
            {
                "id": "transcript-2",
                "video_db_id": "db-2",
                "video_id": "vid-2",
                "video_title": "Video 2",
                "text": "Brazil wins next game",
                "language": "en",
                "source": "youtube",
            },
        ]


class FakeChromaStore:
    def __init__(self) -> None:
        self._indexed = {"vid-1"}
        self.calls: list[str] = []

    def is_indexed(self, video_id: str) -> bool:
        return video_id in self._indexed

    def index_transcript(self, transcript_id: str, video_id: str, text: str, metadata: dict):
        self.calls.append(video_id)
        self._indexed.add(video_id)
        return 2 if transcript_id and text and metadata else 0


def test_index_all_transcripts_skips_already_indexed() -> None:
    summary = index_all_transcripts(FakeRepository(), FakeChromaStore())
    assert summary["available_transcripts"] == 2
    assert summary["indexed_videos"] == 1
    assert summary["skipped_videos"] == 1
    assert summary["indexed_chunks"] == 2

