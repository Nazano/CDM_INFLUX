"""Fetch World Cup match schedules from wheniskickoff.com.

The remote endpoint exposes a ``meta`` object whose fields (typically
``version`` and/or ``generated``) identify the dataset generation.
We persist the last-seen meta to a local cache file so that subsequent
calls can skip processing when the remote data has not changed.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from app.models.entities import Match, Team

logger = logging.getLogger(__name__)

MATCHES_URL = "https://wheniskickoff.com/data/v1/matches.json"
DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "wheniskickoff_meta.json"

_REQUEST_TIMEOUT = 15  # seconds


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_remote_data(url: str = MATCHES_URL, timeout: int = _REQUEST_TIMEOUT) -> dict[str, Any]:
    """Download the JSON payload from *url* and return it as a dictionary.

    Raises:
        urllib.error.URLError: on network errors.
        ValueError: when the response body is not valid JSON or not a mapping.
    """
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected JSON root type from {url}: {type(data).__name__}")
    return data


# ---------------------------------------------------------------------------
# Meta / version helpers
# ---------------------------------------------------------------------------

def extract_meta(data: dict[str, Any]) -> dict[str, Any]:
    """Return the ``meta`` object from *data*, or an empty dict if absent."""
    meta = data.get("meta", {})
    return meta if isinstance(meta, dict) else {}


def is_newer_version(remote_meta: dict[str, Any], cached_meta: dict[str, Any] | None) -> bool:
    """Return *True* when *remote_meta* represents a newer dataset than *cached_meta*.

    Comparison strategy (first match wins):
    1. Compare ``version`` fields if both are present.
    2. Compare ``generated`` / ``generated_at`` / ``last_modified`` timestamp strings.
    3. If no comparable fields exist, always treat the remote as newer so we
       never silently miss updates.
    """
    if not cached_meta:
        return True

    # --- version string comparison ---
    remote_ver = remote_meta.get("version")
    cached_ver = cached_meta.get("version")
    if remote_ver is not None and cached_ver is not None:
        return str(remote_ver) != str(cached_ver)

    # --- timestamp comparison (various field names) ---
    for field in ("generated", "generated_at", "last_modified", "updated_at"):
        remote_ts = remote_meta.get(field)
        cached_ts = cached_meta.get(field)
        if remote_ts and cached_ts:
            return str(remote_ts) != str(cached_ts)

    # Fallback: treat the remote as newer
    return True


# ---------------------------------------------------------------------------
# Cache persistence
# ---------------------------------------------------------------------------

def load_cached_meta(cache_path: Path = DEFAULT_CACHE_PATH) -> dict[str, Any] | None:
    """Load the previously saved meta from *cache_path*, or return *None*."""
    if not cache_path.exists():
        return None
    try:
        raw = cache_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cannot read cached meta from %s: %s", cache_path, exc)
        return None


def save_cached_meta(meta: dict[str, Any], cache_path: Path = DEFAULT_CACHE_PATH) -> None:
    """Persist *meta* to *cache_path* so future runs can skip unchanged data."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Model mapping
# ---------------------------------------------------------------------------

def build_teams_from_remote(data: dict[str, Any]) -> list[Team]:
    """Build :class:`~app.models.entities.Team` objects from the remote payload.

    Handles both a top-level ``teams`` array and team info embedded in the
    match objects themselves.
    """
    teams: dict[str, Team] = {}

    for raw in data.get("teams", []):
        code = raw.get("code") or raw.get("iso") or raw.get("id", "")
        name = raw.get("name") or raw.get("title") or code
        team_id = f"team-{code.lower()}"
        teams[team_id] = Team(id=team_id, name=name, code=code)

    # Derive teams from match participants when no top-level list is provided
    if not teams:
        for raw in data.get("matches", []):
            for side in ("home", "away"):
                name = raw.get(f"{side}Team") or raw.get(f"{side}_team") or ""
                code = raw.get(f"{side}TeamCode") or raw.get(f"{side}_team_code") or ""
                if not name:
                    continue
                team_id = f"team-{(code or name).lower().replace(' ', '-')}"
                if team_id not in teams:
                    teams[team_id] = Team(id=team_id, name=name, code=code or None)

    return list(teams.values())


def build_matches_from_remote(data: dict[str, Any]) -> list[Match]:
    """Convert the remote ``matches`` array into :class:`~app.models.entities.Match` objects."""
    matches: list[Match] = []

    for raw in data.get("matches", []):
        match_id = str(raw.get("id") or raw.get("matchId") or raw.get("match_id", ""))
        if not match_id:
            logger.debug("Skipping match entry with no id: %s", raw)
            continue

        stage = (
            raw.get("stage")
            or raw.get("round")
            or raw.get("phase")
            or raw.get("group")
            or "unknown"
        )

        # Team names (tolerate camelCase and snake_case variants)
        home_name = raw.get("homeTeam") or raw.get("home_team") or raw.get("home") or ""
        away_name = raw.get("awayTeam") or raw.get("away_team") or raw.get("away") or ""
        home_code = raw.get("homeTeamCode") or raw.get("home_team_code") or ""
        away_code = raw.get("awayTeamCode") or raw.get("away_team_code") or ""

        home_id = f"team-{(home_code or home_name).lower().replace(' ', '-')}" if home_name else None
        away_id = f"team-{(away_code or away_name).lower().replace(' ', '-')}" if away_name else None

        # Scheduled time (tolerate various field names and formats)
        scheduled_at = None
        for ts_field in ("kickoff", "kickoffTime", "kickoff_time", "scheduled_at", "datetime", "date"):
            raw_ts = raw.get(ts_field)
            if raw_ts:
                try:
                    scheduled_at = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                except ValueError:
                    logger.debug("Cannot parse timestamp %r for match %s", raw_ts, match_id)
                break

        metadata: dict[str, Any] = {
            "home_team_name": home_name,
            "away_team_name": away_name,
            "home_team_code": home_code,
            "away_team_code": away_code,
            "source": "wheniskickoff",
        }
        if raw.get("venue") or raw.get("stadium"):
            metadata["venue"] = raw.get("venue") or raw.get("stadium")
        if raw.get("city"):
            metadata["city"] = raw["city"]

        matches.append(
            Match(
                id=match_id,
                tournament_stage=str(stage),
                home_team_id=home_id,
                away_team_id=away_id,
                scheduled_at=scheduled_at,
                metadata=metadata,
            )
        )

    return matches


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------

def fetch_matches_if_updated(
    url: str = MATCHES_URL,
    cache_path: Path = DEFAULT_CACHE_PATH,
    force: bool = False,
) -> tuple[list[Match], list[Team], bool]:
    """Fetch matches from the remote endpoint, skipping when data is unchanged.

    Args:
        url: Remote JSON endpoint.
        cache_path: Path to the local file that stores the last-seen ``meta``.
        force: When *True*, skip the version check and always process the data.

    Returns:
        A tuple ``(matches, teams, updated)`` where *updated* is *True* when
        new data was downloaded and processed, and *False* when the cached
        version was already up-to-date and no matches/teams are returned.
    """
    logger.info("Fetching matches from %s", url)
    try:
        data = fetch_remote_data(url)
    except Exception as exc:
        logger.error("Failed to fetch remote matches from %s: %s", url, exc)
        raise

    remote_meta = extract_meta(data)
    cached_meta = load_cached_meta(cache_path)

    if not force and not is_newer_version(remote_meta, cached_meta):
        logger.info(
            "Remote matches data is unchanged (version=%s). Skipping update.",
            remote_meta.get("version") or remote_meta.get("generated"),
        )
        return [], [], False

    matches = build_matches_from_remote(data)
    teams = build_teams_from_remote(data)
    save_cached_meta(remote_meta, cache_path)

    logger.info(
        "Fetched %d matches and %d teams from %s (meta: %s)",
        len(matches),
        len(teams),
        url,
        remote_meta,
    )
    return matches, teams, True
