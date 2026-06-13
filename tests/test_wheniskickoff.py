"""Tests for app/ingestion/wheniskickoff.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ingestion.wheniskickoff import (
    build_matches_from_remote,
    build_teams_from_remote,
    extract_meta,
    fetch_matches_if_updated,
    is_newer_version,
    load_cached_meta,
    save_cached_meta,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DATA: dict = {
    "meta": {
        "version": "2",
        "generated": "2026-06-01T12:00:00Z",
    },
    "matches": [
        {
            "id": "m1",
            "stage": "Group A",
            "homeTeam": "France",
            "awayTeam": "Brazil",
            "homeTeamCode": "FRA",
            "awayTeamCode": "BRA",
            "kickoff": "2026-06-15T18:00:00Z",
            "venue": "MetLife Stadium",
            "city": "New York",
        },
        {
            "id": "m2",
            "round": "Semi-final",
            "home_team": "Germany",
            "away_team": "Argentina",
            "home_team_code": "GER",
            "away_team_code": "ARG",
            "scheduled_at": "2026-07-10T20:00:00Z",
        },
    ],
    "teams": [
        {"code": "FRA", "name": "France"},
        {"code": "BRA", "name": "Brazil"},
    ],
}


# ---------------------------------------------------------------------------
# extract_meta
# ---------------------------------------------------------------------------

def test_extract_meta_returns_meta_dict() -> None:
    meta = extract_meta(SAMPLE_DATA)
    assert meta == {"version": "2", "generated": "2026-06-01T12:00:00Z"}


def test_extract_meta_missing_key_returns_empty() -> None:
    assert extract_meta({}) == {}


def test_extract_meta_non_dict_meta_returns_empty() -> None:
    assert extract_meta({"meta": "v1"}) == {}


# ---------------------------------------------------------------------------
# is_newer_version
# ---------------------------------------------------------------------------

def test_is_newer_version_no_cache_is_newer() -> None:
    assert is_newer_version({"version": "1"}, None) is True


def test_is_newer_version_same_version_not_newer() -> None:
    assert is_newer_version({"version": "2"}, {"version": "2"}) is False


def test_is_newer_version_different_version_is_newer() -> None:
    assert is_newer_version({"version": "3"}, {"version": "2"}) is True


def test_is_newer_version_uses_generated_when_no_version() -> None:
    remote = {"generated": "2026-06-02T00:00:00Z"}
    cached = {"generated": "2026-06-01T00:00:00Z"}
    assert is_newer_version(remote, cached) is True


def test_is_newer_version_same_generated_not_newer() -> None:
    ts = "2026-06-01T00:00:00Z"
    assert is_newer_version({"generated": ts}, {"generated": ts}) is False


def test_is_newer_version_no_comparable_fields_treats_as_newer() -> None:
    assert is_newer_version({}, {}) is True


# ---------------------------------------------------------------------------
# Cache persistence
# ---------------------------------------------------------------------------

def test_save_and_load_cached_meta(tmp_path: Path) -> None:
    cache = tmp_path / "meta.json"
    meta = {"version": "5", "generated": "2026-06-01T00:00:00Z"}
    save_cached_meta(meta, cache)
    loaded = load_cached_meta(cache)
    assert loaded == meta


def test_load_cached_meta_missing_file_returns_none(tmp_path: Path) -> None:
    result = load_cached_meta(tmp_path / "nonexistent.json")
    assert result is None


def test_load_cached_meta_corrupt_file_returns_none(tmp_path: Path) -> None:
    bad = tmp_path / "meta.json"
    bad.write_text("not json", encoding="utf-8")
    assert load_cached_meta(bad) is None


# ---------------------------------------------------------------------------
# build_matches_from_remote
# ---------------------------------------------------------------------------

def test_build_matches_parses_camelCase_fields() -> None:
    matches = build_matches_from_remote(SAMPLE_DATA)
    assert len(matches) == 2

    m1 = next(m for m in matches if m.id == "m1")
    assert m1.tournament_stage == "Group A"
    assert m1.metadata["home_team_name"] == "France"
    assert m1.metadata["away_team_name"] == "Brazil"
    assert m1.metadata["home_team_code"] == "FRA"
    assert m1.metadata["away_team_code"] == "BRA"
    assert m1.metadata["venue"] == "MetLife Stadium"
    assert m1.metadata["city"] == "New York"
    assert m1.metadata["source"] == "wheniskickoff"
    assert m1.scheduled_at is not None
    assert m1.scheduled_at.year == 2026


def test_build_matches_parses_snake_case_fields() -> None:
    matches = build_matches_from_remote(SAMPLE_DATA)
    m2 = next(m for m in matches if m.id == "m2")
    assert m2.tournament_stage == "Semi-final"
    assert m2.metadata["home_team_name"] == "Germany"
    assert m2.metadata["away_team_name"] == "Argentina"
    assert m2.scheduled_at is not None


def test_build_matches_skips_entry_without_id() -> None:
    data = {"matches": [{"stage": "Group A", "homeTeam": "X", "awayTeam": "Y"}]}
    matches = build_matches_from_remote(data)
    assert matches == []


def test_build_matches_empty_list() -> None:
    assert build_matches_from_remote({"matches": []}) == []


def test_build_matches_missing_matches_key() -> None:
    assert build_matches_from_remote({}) == []


# ---------------------------------------------------------------------------
# build_teams_from_remote
# ---------------------------------------------------------------------------

def test_build_teams_from_explicit_list() -> None:
    teams = build_teams_from_remote(SAMPLE_DATA)
    codes = {t.code for t in teams}
    assert "FRA" in codes
    assert "BRA" in codes


def test_build_teams_derived_from_matches_when_no_top_level_list() -> None:
    data = {
        "matches": [
            {
                "id": "x1",
                "homeTeam": "Spain",
                "homeTeamCode": "ESP",
                "awayTeam": "Portugal",
                "awayTeamCode": "POR",
            }
        ]
    }
    teams = build_teams_from_remote(data)
    names = {t.name for t in teams}
    assert "Spain" in names
    assert "Portugal" in names


# ---------------------------------------------------------------------------
# fetch_matches_if_updated (integration, no network)
# ---------------------------------------------------------------------------

def test_fetch_matches_if_updated_no_update_when_same_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = {"version": "1"}
    cache = tmp_path / "meta.json"
    save_cached_meta(meta, cache)

    def fake_fetch(url, timeout=15):
        return {"meta": meta, "matches": [{"id": "m1", "stage": "G", "homeTeam": "A", "awayTeam": "B"}]}

    monkeypatch.setattr("app.ingestion.wheniskickoff.fetch_remote_data", fake_fetch)

    matches, teams, updated = fetch_matches_if_updated(cache_path=cache)
    assert updated is False
    assert matches == []
    assert teams == []


def test_fetch_matches_if_updated_returns_data_when_version_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "meta.json"
    save_cached_meta({"version": "1"}, cache)

    def fake_fetch(url, timeout=15):
        return {
            "meta": {"version": "2"},
            "matches": [{"id": "m1", "stage": "Group A", "homeTeam": "France", "awayTeam": "Brazil"}],
        }

    monkeypatch.setattr("app.ingestion.wheniskickoff.fetch_remote_data", fake_fetch)

    matches, teams, updated = fetch_matches_if_updated(cache_path=cache)
    assert updated is True
    assert len(matches) == 1
    # Cache should now reflect the new version
    assert load_cached_meta(cache) == {"version": "2"}


def test_fetch_matches_if_updated_force_always_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = {"version": "1"}
    cache = tmp_path / "meta.json"
    save_cached_meta(meta, cache)

    def fake_fetch(url, timeout=15):
        return {"meta": meta, "matches": [{"id": "m1", "stage": "G", "homeTeam": "A", "awayTeam": "B"}]}

    monkeypatch.setattr("app.ingestion.wheniskickoff.fetch_remote_data", fake_fetch)

    matches, teams, updated = fetch_matches_if_updated(cache_path=cache, force=True)
    assert updated is True
    assert len(matches) == 1


def test_fetch_matches_if_updated_propagates_network_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.error

    cache = tmp_path / "meta.json"

    def fake_fetch(url, timeout=15):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("app.ingestion.wheniskickoff.fetch_remote_data", fake_fetch)

    with pytest.raises(urllib.error.URLError):
        fetch_matches_if_updated(cache_path=cache)
