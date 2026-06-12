from app.config import DEFAULT_CONFIG_PATH, load_app_config


def test_load_app_config_reads_channels() -> None:
    config = load_app_config(DEFAULT_CONFIG_PATH)
    assert len(config.channels) == 3
    assert config.channels[0].language == "fr"
