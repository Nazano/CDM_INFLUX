from app.config import DEFAULT_CONFIG_PATH, Settings, load_app_config, load_env_file


def test_load_app_config_reads_channels() -> None:
    config = load_app_config(DEFAULT_CONFIG_PATH)
    assert len(config.channels) == 3
    assert config.channels[0].url == "https://www.youtube.com/@liberopod"
    assert config.channels[1].language == "fr"
    assert config.channels[2].name == "SBS Sport AU"


def test_load_env_file_populates_youtube_settings(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "YOUTUBE_API_KEY=test-key\n"
        "YOUTUBE_CAPTIONS_OAUTH_TOKEN=test-oauth\n"
        "YOUTUBE_MAX_RESULTS=7\n"
        "YOUTUBE_CAPTION_BATCH_SIZE=4\n"
        "YOUTUBE_TRANSCRIPT_FALLBACK_DELAY_SECONDS=12\n",
        encoding="utf-8",
    )

    load_env_file(env_path)
    settings = Settings()

    assert settings.youtube_api_key == "test-key"
    assert settings.youtube_captions_oauth_token == "test-oauth"
    assert settings.youtube_max_results == 7
    assert settings.youtube_caption_batch_size == 4
    assert settings.youtube_transcript_fallback_delay_seconds == 12


def test_load_env_file_overrides_existing_env_var(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_API_KEY", "old-key")
    env_path = tmp_path / ".env"
    env_path.write_text("YOUTUBE_API_KEY=new-key\n", encoding="utf-8")

    load_env_file(env_path)
    settings = Settings()

    assert settings.youtube_api_key == "new-key"
