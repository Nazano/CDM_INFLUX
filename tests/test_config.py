from app.config import DEFAULT_CONFIG_PATH, Settings, load_app_config, load_env_file


def test_load_app_config_reads_channels() -> None:
    config = load_app_config(DEFAULT_CONFIG_PATH)
    assert len(config.channels) == 3
    assert config.channels[0].language == "fr"


def test_load_env_file_populates_youtube_settings(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("YOUTUBE_API_KEY=test-key\nYOUTUBE_MAX_RESULTS=7\n", encoding="utf-8")
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_MAX_RESULTS", raising=False)

    load_env_file(env_path)
    settings = Settings()

    assert settings.youtube_api_key == "test-key"
    assert settings.youtube_max_results == 7
