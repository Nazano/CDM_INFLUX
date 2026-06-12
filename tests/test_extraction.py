from app.extraction.predictions import extract_predictions
from app.extraction.transcripts import extract_transcript


def test_extract_transcript_uses_hint_when_available() -> None:
    transcript = extract_transcript("video-123", transcript_hint="Brazil will win the World Cup.", language="en")
    assert transcript.status == "available"
    assert transcript.text == "Brazil will win the World Cup."
    assert transcript.segments


def test_extract_transcript_fetches_youtube_transcript(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.extraction.transcripts._fetch_youtube_transcript",
        lambda video_id, language: {
            "language": "fr",
            "segments": extract_transcript("demo", transcript_hint="Bonjour le monde", language="fr").segments,
            "source": "youtube",
        },
    )

    transcript = extract_transcript("video-123", language="fr")

    assert transcript.status == "available"
    assert transcript.source == "youtube"
    assert transcript.text == "Bonjour le monde"


def test_extract_transcript_marks_unavailable_when_fetch_fails(monkeypatch) -> None:
    from youtube_transcript_api import NoTranscriptFound

    def raise_not_found(video_id: str, language: str | None):
        raise NoTranscriptFound(video_id, [language or "en"], None)

    monkeypatch.setattr("app.extraction.transcripts._fetch_youtube_transcript", raise_not_found)

    transcript = extract_transcript("video-123", language="fr")

    assert transcript.status == "unavailable"
    assert transcript.text is None


def test_extract_predictions_detects_winner_and_score() -> None:
    extracted = extract_predictions(
        "Brazil will win the World Cup. Brazil 3-2 Spain because their attack depth is unmatched."
    )
    item_types = {item.item_type for item in extracted.items}
    assert "tournament_winner" in item_types
    assert "exact_score" in item_types
    assert any(item.value == "Brazil" for item in extracted.items if item.item_type == "tournament_winner")
