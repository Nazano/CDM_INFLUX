from app.extraction.predictions import extract_predictions
from app.extraction.transcripts import extract_transcript


def test_extract_transcript_uses_hint_when_available() -> None:
    transcript = extract_transcript("video-123", transcript_hint="Brazil will win the World Cup.", language="en")
    assert transcript.status == "available"
    assert transcript.text == "Brazil will win the World Cup."
    assert transcript.segments


def test_extract_predictions_detects_winner_and_score() -> None:
    extracted = extract_predictions(
        "Brazil will win the World Cup. Brazil 3-2 Spain because their attack depth is unmatched."
    )
    item_types = {item.item_type for item in extracted.items}
    assert "tournament_winner" in item_types
    assert "exact_score" in item_types
    assert any(item.value == "Brazil" for item in extracted.items if item.item_type == "tournament_winner")
