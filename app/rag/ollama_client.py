from __future__ import annotations

from typing import Any


def get_embedding(text: str, *, model: str, host: str) -> list[float]:
    try:
        import ollama
    except ImportError as exc:
        raise RuntimeError("ollama is required for RAG. Install dependencies first.") from exc
    response = ollama.embed(model=model, input=text, host=host)
    embeddings = response.get("embeddings") or []
    if not embeddings:
        raise RuntimeError("No embedding returned by Ollama.")
    return embeddings[0]


def chat_completion(prompt: str, *, model: str, host: str) -> str:
    try:
        import ollama
    except ImportError as exc:
        raise RuntimeError("ollama is required for RAG. Install dependencies first.") from exc
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
        options={"temperature": 0.2},
        keep_alive="10m",
        host=host,
    )
    return ((response.get("message") or {}).get("content") or "").strip()


def rag_query(
    question: str,
    retrieved_chunks: list[dict[str, Any]],
    *,
    model: str,
    host: str,
) -> str:
    if not retrieved_chunks:
        return "Aucun contexte trouvé dans la base de connaissances."
    context_parts: list[str] = []
    for index, item in enumerate(retrieved_chunks, start=1):
        metadata = item.get("metadata") or {}
        source = metadata.get("video_title") or metadata.get("video_id") or "source inconnue"
        chunk = item.get("document") or ""
        context_parts.append(f"[{index}] Source: {source}\n{chunk}")
    prompt = (
        "Tu es un assistant analytique pour des transcripts de vidéos de pronostics football.\n"
        "Réponds uniquement à partir du contexte ci-dessous. Si l'information manque, dis-le clairement.\n\n"
        f"Question: {question}\n\n"
        "Contexte:\n"
        f"{'\n\n'.join(context_parts)}\n\n"
        "Réponse concise en français:"
    )
    return chat_completion(prompt, model=model, host=host)

