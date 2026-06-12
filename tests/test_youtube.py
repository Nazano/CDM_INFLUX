from app.config import ChannelConfig
from app.ingestion.youtube import RealYouTubeSource, extract_youtube_channel_id, extract_youtube_handle, parse_iso8601_duration


class StubYouTubeSource(RealYouTubeSource):
    def __init__(self, responses: dict[str, dict]) -> None:
        super().__init__("test-key", max_results=5)
        self.responses = responses

    def _fetch_json(self, resource: str, params: dict[str, object]) -> dict[str, object]:
        return self.responses[resource]


def test_extract_youtube_identifiers() -> None:
    assert extract_youtube_handle("https://www.youtube.com/@footvisionfr") == "footvisionfr"
    assert extract_youtube_handle("https://www.youtube.com/c/legacychannel") == "legacychannel"
    assert extract_youtube_channel_id("https://www.youtube.com/channel/UC123456789") == "UC123456789"


def test_parse_iso8601_duration() -> None:
    assert parse_iso8601_duration("PT1H2M3S") == 3723
    assert parse_iso8601_duration("PT45S") == 45
    assert parse_iso8601_duration("P1DT2H") is None


def test_real_youtube_source_maps_recent_videos() -> None:
    source = StubYouTubeSource(
        {
            "channels": {"items": [{"id": "UC123"}]},
            "search": {"items": [{"id": {"videoId": "abc123"}}]},
            "videos": {
                "items": [
                    {
                        "id": "abc123",
                        "snippet": {
                            "title": "World Cup 2026 prediction",
                            "description": "France to reach the final.",
                            "publishedAt": "2026-01-01T10:00:00Z",
                            "tags": ["world cup 2026", "prediction"],
                        },
                        "contentDetails": {"duration": "PT12M5S"},
                    }
                ]
            },
        }
    )
    channel = ChannelConfig(
        id="channel-fr-foot-vision",
        name="Foot Vision FR",
        url="https://www.youtube.com/@footvisionfr",
        language="fr",
        keywords=["coupe du monde 2026"],
    )

    videos = source.get_recent_videos_for_channel(channel)

    assert len(videos) == 1
    assert videos[0]["channel_id"] == channel.id
    assert videos[0]["youtube_channel_id"] == "UC123"
    assert videos[0]["video_url"] == "https://www.youtube.com/watch?v=abc123"
    assert videos[0]["duration_seconds"] == 725
