from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.rag.ollama_client import chat_completion


def enrich_predictions_with_ollama(transcript_text: str, base_payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.rag_enabled:
        return {
            "enabled": False,
            "reason": "RAG/Ollama disabled.",
            "base_payload": base_payload,
            "transcript_excerpt": transcript_text[:280],
        }
    prompt = (
        "Résume les signaux de pronostics du transcript suivant en 3 points max.\n"
        "Retourne du texte brut en français.\n\n"
        f"Transcript:\n{transcript_text[:4000]}"
    )
    try:
        llm_summary = chat_completion(
            prompt,
            model=settings.ollama_chat_model,
            host=settings.ollama_base_url,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "reason": f"Ollama unavailable: {exc}",
            "base_payload": base_payload,
            "transcript_excerpt": transcript_text[:280],
        }
    return {
        "enabled": True,
        "model": settings.ollama_chat_model,
        "base_payload": base_payload,
        "llm_summary": llm_summary,
    }
