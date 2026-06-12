from __future__ import annotations

import re
import uuid
from typing import Any

from app.extraction.llm import enrich_predictions_with_ollama
from app.models.entities import ExtractedPredictions, PredictionItem
from app.utils.text import sentence_split

TEAMS = [
    "Argentina",
    "Brazil",
    "France",
    "Spain",
    "England",
    "Germany",
    "Portugal",
    "Mexico",
    "Morocco",
    "Uruguay",
    "USA",
    "Canada",
]

WINNER_PATTERNS = [
    re.compile(r"(?P<team>[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)*) (?:will win|wins|gagnera|ganará) (?:the )?(?:world cup|coupe du monde|mundial)", re.IGNORECASE),
    re.compile(r"(?:world cup|coupe du monde|mundial) (?:winner|vainqueur|ganador)[^A-Za-z]+(?P<team>[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)*)", re.IGNORECASE),
]
SCORE_PATTERN = re.compile(
    r"(?P<home>[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)*)\s(?P<home_score>\d)\s*[-:]\s*(?P<away_score>\d)\s(?P<away>[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)*)",
    re.IGNORECASE,
)
QUALIFIED_PATTERN = re.compile(r"(?P<team>[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)*) (?:qualify|qualified|qualifiée|clasifica|clasificado)", re.IGNORECASE)
CONFIDENCE_TERMS = {
    0.85: ["definitely", "certain", "très sûr", "muy seguro", "lock"],
    0.65: ["likely", "probable", "je pense", "creo", "probably"],
    0.45: ["maybe", "peut-être", "quizá", "possibly"],
}


def extract_predictions(transcript_text: str) -> ExtractedPredictions:
    sentences = sentence_split(transcript_text)
    items: list[PredictionItem] = []
    key_quotes: list[str] = []

    for sentence in sentences:
        stripped = sentence.strip()
        lowered = stripped.casefold()
        sentence_confidence = _estimate_confidence(lowered)

        for pattern in WINNER_PATTERNS:
            match = pattern.search(stripped)
            if match:
                team = match.group("team").strip()
                items.append(
                    _build_item(
                        item_type="tournament_winner",
                        subject="World Cup 2026",
                        value=team,
                        confidence=sentence_confidence,
                        rationale="Tournament winner heuristic.",
                        quote=stripped,
                    )
                )
                key_quotes.append(stripped)

        for match in SCORE_PATTERN.finditer(stripped):
            home_team = match.group("home").strip()
            away_team = match.group("away").strip()
            home_score = match.group("home_score")
            away_score = match.group("away_score")
            winner = _determine_match_winner(home_team, away_team, home_score, away_score)
            match_label = f"{home_team} vs {away_team}"
            items.extend(
                [
                    _build_item(
                        item_type="exact_score",
                        subject=match_label,
                        value=f"{home_score}-{away_score}",
                        confidence=sentence_confidence,
                        rationale="Exact score pattern match.",
                        quote=stripped,
                        metadata={"home_team": home_team, "away_team": away_team},
                    ),
                    _build_item(
                        item_type="match_winner",
                        subject=match_label,
                        value=winner,
                        confidence=sentence_confidence,
                        rationale="Winner inferred from exact score.",
                        quote=stripped,
                        metadata={"home_team": home_team, "away_team": away_team},
                    ),
                ]
            )
            key_quotes.append(stripped)

        for match in QUALIFIED_PATTERN.finditer(stripped):
            team = match.group("team").strip()
            items.append(
                _build_item(
                    item_type="qualified_team",
                    subject="Qualification",
                    value=team,
                    confidence=sentence_confidence,
                    rationale="Qualification keyword match.",
                    quote=stripped,
                )
            )

        if any(team.casefold() in lowered for team in TEAMS) and any(token in lowered for token in ["because", "car", "porque", "due to"]):
            items.append(
                _build_item(
                    item_type="argument",
                    subject="Argument",
                    value=stripped,
                    confidence=sentence_confidence,
                    rationale="Sentence contains team mention and rationale marker.",
                    quote=stripped,
                )
            )

        if any(term in lowered for terms in CONFIDENCE_TERMS.values() for term in terms):
            items.append(
                _build_item(
                    item_type="confidence_signal",
                    subject="Confidence",
                    value=stripped,
                    confidence=sentence_confidence,
                    rationale="Confidence marker detected.",
                    quote=stripped,
                )
            )

    deduped_quotes = list(dict.fromkeys(key_quotes))[:5]
    overall_confidence = round(sum(item.confidence for item in items) / len(items), 2) if items else 0.35
    summary = _build_summary(items)
    llm_hint = enrich_predictions_with_ollama(transcript_text, {"summary": summary, "item_count": len(items)})
    return ExtractedPredictions(
        summary=summary,
        confidence=overall_confidence,
        items=items,
        key_quotes=deduped_quotes,
        metadata={"llm_hint": llm_hint},
    )


def _build_item(
    *,
    item_type: str,
    subject: str | None,
    value: str,
    confidence: float,
    rationale: str,
    quote: str,
    metadata: dict[str, Any] | None = None,
) -> PredictionItem:
    return PredictionItem(
        id=f"item-{uuid.uuid4().hex[:12]}",
        prediction_id="",
        item_type=item_type,
        subject=subject,
        value=value,
        confidence=round(confidence, 2),
        rationale=rationale,
        quote=quote,
        metadata=metadata or {},
    )


def _estimate_confidence(sentence: str) -> float:
    for confidence, keywords in CONFIDENCE_TERMS.items():
        if any(keyword in sentence for keyword in keywords):
            return confidence
    return 0.55


def _determine_match_winner(home_team: str, away_team: str, home_score: str, away_score: str) -> str:
    home_value = int(home_score)
    away_value = int(away_score)
    if home_value > away_value:
        return home_team
    if away_value > home_value:
        return away_team
    return "Draw"


def _build_summary(items: list[PredictionItem]) -> str:
    if not items:
        return "No structured predictions were detected in the transcript."
    winners = [item.value for item in items if item.item_type == "tournament_winner"]
    exact_scores = [f"{item.subject}: {item.value}" for item in items if item.item_type == "exact_score"]
    summary_parts = []
    if winners:
        summary_parts.append(f"Tournament winner picks: {', '.join(dict.fromkeys(winners))}.")
    if exact_scores:
        summary_parts.append(f"Exact scores detected: {'; '.join(exact_scores[:3])}.")
    summary_parts.append(f"Total structured items: {len(items)}.")
    return " ".join(summary_parts)
