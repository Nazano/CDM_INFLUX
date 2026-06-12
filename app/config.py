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


class ChannelConfig(BaseModel):
    id: str
    name: str
    url: str
    language: str
    region: str | None = None
    active: bool = True
    keywords: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    channels: list[ChannelConfig] = Field(default_factory=list)


class Settings(BaseModel):
    config_path: Path = DEFAULT_CONFIG_PATH
    demo_data_path: Path = DEFAULT_DATA_PATH
    db_path: Path = Field(default_factory=lambda: Path(os.getenv("CDM_INFLUX_DB_PATH", DEFAULT_DB_PATH)))


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
    return Settings()
