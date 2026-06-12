from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "channels.yml"
DEFAULT_DATA_PATH = REPO_ROOT / "data" / "demo_videos.json"
DEFAULT_DB_PATH = REPO_ROOT / "data" / "cdm_influx.db"
DEFAULT_ENV_PATH = REPO_ROOT / ".env"


class ChannelConfig(BaseModel):
    id: str
    name: str
    url: str
    language: str
    region: str | None = None
    active: bool = True
    youtube_channel_id: str | None = None
    keywords: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    channels: list[ChannelConfig] = Field(default_factory=list)


class Settings(BaseModel):
    config_path: Path = DEFAULT_CONFIG_PATH
    demo_data_path: Path = DEFAULT_DATA_PATH
    db_path: Path = Field(default_factory=lambda: Path(os.getenv("CDM_INFLUX_DB_PATH", DEFAULT_DB_PATH)))
    youtube_api_key: str | None = Field(default_factory=lambda: os.getenv("YOUTUBE_API_KEY"))
    youtube_max_results: int = Field(default_factory=lambda: int(os.getenv("YOUTUBE_MAX_RESULTS", "10")))
    youtube_transcripts_enabled: bool = Field(
        default_factory=lambda: os.getenv("YOUTUBE_TRANSCRIPTS_ENABLED", "false").lower() in {"1", "true", "yes"}
    )


def load_env_file(path: Path = DEFAULT_ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ[key] = value


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        content = yaml.safe_load(handle) or {}
    if not isinstance(content, dict):
        raise ValueError(f"Configuration file must contain a mapping: {path}")
    return content


def load_app_config(path: Path | None = None) -> AppConfig:
    raw = load_yaml_file(path or DEFAULT_CONFIG_PATH)
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid application configuration: {exc}") from exc


def get_settings() -> Settings:
    load_env_file()
    return Settings()
