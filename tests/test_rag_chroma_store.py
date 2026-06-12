from __future__ import annotations

from app.rag.chroma_store import ChromaStore


class FakeCollection:
    def __init__(self) -> None:
        self._items: dict[str, dict] = {}

    def get(self, where: dict | None = None, limit: int | None = None):
        if not where:
            ids = list(self._items.keys())
            return {"ids": ids[:limit] if limit else ids}
        filtered = [
            item_id
            for item_id, item in self._items.items()
            if all(item["metadata"].get(key) == value for key, value in where.items())
        ]
        return {"ids": filtered[:limit] if limit else filtered}

    def upsert(self, ids, documents, embeddings, metadatas):
        for item_id, document, embedding, metadata in zip(ids, documents, embeddings, metadatas):
            self._items[item_id] = {"document": document, "embedding": embedding, "metadata": metadata}

    def query(self, query_embeddings, n_results, where=None):
        _ = query_embeddings
        rows = []
        for item_id, payload in self._items.items():
            if where and any(payload["metadata"].get(key) != value for key, value in where.items()):
                continue
            rows.append((item_id, payload))
        rows = rows[:n_results]
        return {
            "ids": [[item_id for item_id, _ in rows]],
            "documents": [[payload["document"] for _, payload in rows]],
            "metadatas": [[payload["metadata"] for _, payload in rows]],
            "distances": [[0.1 for _ in rows]],
        }


def test_chroma_store_is_indexed_and_query() -> None:
    collection = FakeCollection()
    store = ChromaStore(
        "unused",
        ollama_base_url="http://localhost:11434",
        embed_model="nomic-embed-text",
        collection=collection,
        embedding_fn=lambda text: [float(len(text))],
    )

    count = store.index_transcript(
        "transcript-abc",
        "video-123",
        "France gagnera le match. Brazil reste dangereux.",
        metadata={"video_title": "Test title", "match_id": "match-1"},
    )
    assert count >= 1
    assert store.is_indexed("video-123") is True
    results = store.query("Qui va gagner ?", n_results=3, filter_metadata={"match_id": "match-1"})
    assert results
    assert results[0]["metadata"]["video_id"] == "video-123"

