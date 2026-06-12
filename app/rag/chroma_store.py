from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def chunk_text(text: str, *, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    words = text.split()
    if not words:
        return []
    if chunk_size <= chunk_overlap:
        raise ValueError("chunk_size must be greater than chunk_overlap")
    chunks: list[str] = []
    step = chunk_size - chunk_overlap
    for index in range(0, len(words), step):
        chunk_words = words[index:index + chunk_size]
        if not chunk_words:
            continue
        chunks.append(" ".join(chunk_words))
        if index + chunk_size >= len(words):
            break
    return chunks


class ChromaStore:
    def __init__(
        self,
        chroma_path: Path | str,
        *,
        ollama_base_url: str,
        embed_model: str,
        collection_name: str = "transcripts",
        embedding_fn: Callable[[str], list[float]] | None = None,
        collection: Any | None = None,
    ) -> None:
        self.chroma_path = str(chroma_path)
        self.ollama_base_url = ollama_base_url
        self.embed_model = embed_model
        self.collection_name = collection_name
        self._embedding_fn = embedding_fn
        self._collection = collection

        if self._collection is None:
            self._collection = self._build_collection()

    def _build_collection(self) -> Any:
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError("chromadb is required for RAG indexing. Install dependencies first.") from exc

        client = chromadb.PersistentClient(path=self.chroma_path)
        return client.get_or_create_collection(name=self.collection_name)

    def _embed(self, text: str) -> list[float]:
        if self._embedding_fn:
            return self._embedding_fn(text)
        try:
            import ollama
        except ImportError as exc:
            raise RuntimeError("ollama is required for embeddings. Install dependencies first.") from exc
        response = ollama.embed(
            model=self.embed_model,
            input=text,
            host=self.ollama_base_url,
        )
        embeddings = response.get("embeddings") or []
        if not embeddings:
            raise RuntimeError("No embedding returned by Ollama.")
        return embeddings[0]

    def is_indexed(self, video_id: str) -> bool:
        result = self._collection.get(where={"video_id": video_id}, limit=1)
        ids = result.get("ids") or []
        return bool(ids)

    def index_transcript(
        self,
        transcript_id: str,
        video_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        content = (text or "").strip()
        if not content:
            return 0
        chunks = chunk_text(content)
        if not chunks:
            return 0

        ids: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            ids.append(f"{transcript_id}:{index}")
            embeddings.append(self._embed(chunk))
            item_metadata = {"video_id": video_id, "transcript_id": transcript_id, "chunk_index": index}
            if metadata:
                item_metadata.update(metadata)
            metadatas.append(item_metadata)

        self._collection.upsert(
            ids=ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        return len(chunks)

    def query(
        self,
        question: str,
        *,
        n_results: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        embedding = self._embed(question)
        response = self._collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where=filter_metadata or None,
        )
        documents = (response.get("documents") or [[]])[0]
        metadatas = (response.get("metadatas") or [[]])[0]
        distances = (response.get("distances") or [[]])[0]
        ids = (response.get("ids") or [[]])[0]
        return [
            {
                "id": ids[index] if index < len(ids) else None,
                "document": documents[index],
                "metadata": metadatas[index] if index < len(metadatas) else {},
                "distance": distances[index] if index < len(distances) else None,
            }
            for index in range(len(documents))
        ]

