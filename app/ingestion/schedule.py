from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models.entities import Match, Team

logger = logging.getLogger(__name__)


def load_schedule(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_teams(schedule: dict[str, Any]) -> list[Team]:
    return [
        Team(id=f"team-{entry['code'].lower()}", name=entry["name"], code=entry["code"])
        for entry in schedule.get("teams", [])
    ]


def build_matches(schedule: dict[str, Any]) -> list[Match]:
    team_by_name: dict[str, str] = {
        entry["name"]: f"team-{entry['code'].lower()}"
        for entry in schedule.get("teams", [])
    }

    matches: list[Match] = []
    for raw in schedule.get("matches", []):
        home_id = team_by_name.get(raw["home_team"])
        away_id = team_by_name.get(raw["away_team"])
        scheduled_at: datetime | None = None
        if raw.get("scheduled_at"):
            try:
                scheduled_at = datetime.fromisoformat(raw["scheduled_at"])
            except ValueError:
                logger.warning("Cannot parse scheduled_at for match %s: %s", raw["id"], raw["scheduled_at"])

        metadata: dict[str, Any] = {}
        if raw.get("venue"):
            metadata["venue"] = raw["venue"]
        metadata["home_team_name"] = raw["home_team"]
        metadata["away_team_name"] = raw["away_team"]
        metadata["home_team_code"] = raw.get("home_team_code", "")
        metadata["away_team_code"] = raw.get("away_team_code", "")

        matches.append(
            Match(
                id=raw["id"],
                tournament_stage=raw["stage"],
                home_team_id=home_id,
                away_team_id=away_id,
                scheduled_at=scheduled_at,
                metadata=metadata,
            )
        )
    return matches


def build_youtube_search_queries(match: Match) -> list[tuple[str, str]]:
    """Return a list of (query, language) tuples to search on YouTube for this match."""
    home = match.metadata.get("home_team_name", "")
    away = match.metadata.get("away_team_name", "")
    if not home or not away or home == "À déterminer":
        return []
    queries = [
        (f"pronostic {home} {away} coupe du monde 2026", "fr"),
        (f"prediction {home} {away} world cup 2026", "en"),
        (f"pronostic {away} {home} coupe du monde 2026", "fr"),
        (f"prediction {away} {home} world cup 2026", "en"),
    ]
    return queries
