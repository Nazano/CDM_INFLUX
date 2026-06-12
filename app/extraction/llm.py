from __future__ import annotations

from typing import Any


# TODO: implement optional local Ollama enrichment for prediction extraction.
def enrich_predictions_with_ollama(transcript_text: str, base_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": False,
        "reason": "Ollama enrichment not configured in v1.",
        "base_payload": base_payload,
        "transcript_excerpt": transcript_text[:280],
    }
