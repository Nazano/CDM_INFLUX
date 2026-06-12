from __future__ import annotations

import re
from collections.abc import Iterable


WORLD_CUP_KEYWORDS = {
    "en": ["world cup 2026", "fifa 2026", "2026 world cup", "qualification", "group stage"],
    "fr": ["coupe du monde 2026", "mondial 2026", "qualifiés", "phase de groupes"],
    "es": ["mundial 2026", "copa del mundo 2026", "clasificados", "fase de grupos"],
}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def sentence_split(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def contains_keywords(text: str, language: str, extra_keywords: Iterable[str] | None = None) -> bool:
    haystack = normalize_text(text)
    keywords = list(WORLD_CUP_KEYWORDS.get(language, [])) + list(extra_keywords or [])
    return any(normalize_text(keyword) in haystack for keyword in keywords)
