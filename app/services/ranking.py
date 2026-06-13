from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


def rank_predictions(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"score": 0.0, "votes": 0, "contributors": set()})
    now = datetime.now(timezone.utc)
    for prediction in predictions:
        created_at = prediction.get("publish_date") or prediction.get("created_at")
        if isinstance(created_at, str):
            try:
                published = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                published = now
        elif isinstance(created_at, datetime):
            published = created_at
        else:
            published = now
        age_days = max((now - published).days, 0)
        freshness = max(0.3, 1 - min(age_days, 365) / 365)
        creator_weight = float(prediction.get("creator_weight", 1.0))
        historical_accuracy = float(prediction.get("historical_accuracy", 0.5))
        confidence = float(prediction.get("confidence", 0.5))
        group_key = (prediction.get("subject", "Unknown"), prediction.get("value", "Unknown"))
        grouped[group_key]["score"] += round(creator_weight * historical_accuracy * freshness * confidence, 4)
        grouped[group_key]["votes"] += 1
        grouped[group_key]["contributors"].add(prediction.get("creator_name", "Unknown"))

    ranked = []
    for (subject, value), aggregate in grouped.items():
        ranked.append(
            {
                "subject": subject,
                "value": value,
                "consensus_score": round(aggregate["score"], 4),
                "votes": aggregate["votes"],
                "contributors": sorted(aggregate["contributors"]),
            }
        )
    return sorted(ranked, key=lambda item: (item["subject"], -item["consensus_score"], -item["votes"]))
