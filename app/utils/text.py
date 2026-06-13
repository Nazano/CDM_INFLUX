from __future__ import annotations

import re
from collections.abc import Iterable


WORLD_CUP_KEYWORDS = {
    "en": ["world cup", "fifa world cup", "world cup 2026", "2026 world cup", "fifa 2026", "qualification", "group stage"],
    "fr": ["coupe du monde", "mondial", "coupe du monde 2026", "mondial 2026", "qualifiés", "qualifications", "phase de groupes"],
    "es": ["mundial", "copa del mundo", "mundial 2026", "copa del mundo 2026", "clasificados", "clasificación", "fase de grupos"],
}
WORLD_CUP_SEARCH_TERMS = {
    "en": "world cup",
    "fr": "coupe du monde",
    "es": "mundial",
}
NEGATED_WORLD_CUP_PATTERNS = {
    "en": [r"\bnothing related to the world cup\b", r"\bnot related to the world cup\b", r"\bnot about the world cup\b"],
    "fr": [r"\brien sur la coupe du monde\b", r"\bpas lié à la coupe du monde\b", r"\bpas sur la coupe du monde\b"],
    "es": [r"\bnada sobre el mundial\b", r"\bno trata del mundial\b", r"\bno va sobre la copa del mundo\b"],
}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def sentence_split(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def contains_keywords(text: str, language: str, extra_keywords: Iterable[str] | None = None) -> bool:
    haystack = normalize_text(text)
    keywords = list(WORLD_CUP_KEYWORDS.get(language, [])) + list(extra_keywords or [])
    return any(normalize_text(keyword) in haystack for keyword in keywords)


def build_world_cup_search_query(language: str) -> str:
    return WORLD_CUP_SEARCH_TERMS.get(language, "world cup")


def has_negated_world_cup_context(text: str, language: str) -> bool:
    haystack = normalize_text(text)
    return any(re.search(pattern, haystack) for pattern in NEGATED_WORLD_CUP_PATTERNS.get(language, []))
