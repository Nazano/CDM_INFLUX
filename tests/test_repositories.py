from datetime import datetime

from app.models.entities import Channel, Creator, ExtractedPredictions, Match, Prediction, PredictionItem, Team, Transcript, TranscriptSegment, Video
from app.storage.database import Database
from app.storage.repositories import Repository


def test_repository_persists_video_prediction_and_transcript(tmp_path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    repository = Repository(database)

    creator = Creator(id="creator-1", name="Creator", language="en")
    channel = Channel(id="channel-1", creator_id=creator.id, name="Channel", url="https://example.com", language="en")
    video = Video(
        id="video-1",
        channel_id=channel.id,
        creator_id=creator.id,
        video_id="abc123",
        video_url="https://youtube.com/watch?v=abc123",
        title="World Cup 2026 picks",
        description="desc",
        publish_date=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        language="en",
    )
    transcript = Transcript(
        id="transcript-1",
        video_id=video.id,
        status="available",
        text="Brazil will win the World Cup.",
        language="en",
        segments=[TranscriptSegment(start_seconds=0, end_seconds=5, text="Brazil will win the World Cup")],
    )
    prediction = Prediction(
        id="prediction-1",
        video_id=video.id,
        transcript_id=transcript.id,
        language="en",
        summary="Brazil is picked as champion.",
        confidence=0.75,
    )
    item = PredictionItem(
        id="item-1",
        prediction_id=prediction.id,
        item_type="tournament_winner",
        subject="World Cup 2026",
        value="Brazil",
        confidence=0.75,
    )
    extracted = ExtractedPredictions(summary=prediction.summary, confidence=prediction.confidence, items=[item])

    repository.upsert_creator(creator)
    repository.upsert_channel(channel)
    repository.upsert_video(video)
    repository.save_transcript(transcript)
    repository.save_prediction(prediction, extracted)

    metrics = repository.get_overview_metrics()
    detail = repository.get_video_detail(video.id)

    assert metrics["videos"] == 1
    assert detail is not None
    assert detail["prediction"]["summary"] == "Brazil is picked as champion."
    assert detail["prediction_items"][0]["value"] == "Brazil"


def test_repository_get_matches_includes_analysis_status_and_predicted_score(tmp_path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    repository = Repository(database)

    home_team = Team(id="team-fra", name="France", code="FRA")
    away_team = Team(id="team-bra", name="Brazil", code="BRA")
    match = Match(
        id="match-1",
        tournament_stage="Group A",
        home_team_id=home_team.id,
        away_team_id=away_team.id,
        scheduled_at=datetime.fromisoformat("2026-06-15T18:00:00+00:00"),
        metadata={"home_team_name": "France", "away_team_name": "Brazil"},
    )
    creator = Creator(id="creator-1", name="Creator", language="en")
    channel = Channel(id="channel-1", creator_id=creator.id, name="Channel", url="https://example.com", language="en")
    video = Video(
        id="video-1",
        channel_id=channel.id,
        creator_id=creator.id,
        video_id="abc123",
        video_url="https://youtube.com/watch?v=abc123",
        title="France vs Brazil preview",
        description="desc",
        publish_date=datetime.fromisoformat("2026-06-10T00:00:00+00:00"),
        language="en",
    )
    transcript = Transcript(
        id="transcript-1",
        video_id=video.id,
        status="available",
        text="France 2-1 Brazil",
        language="en",
        segments=[TranscriptSegment(start_seconds=0, end_seconds=5, text="France 2-1 Brazil")],
    )
    prediction = Prediction(
        id="prediction-1",
        video_id=video.id,
        transcript_id=transcript.id,
        language="en",
        summary="France wins 2-1.",
        confidence=0.8,
    )
    items = [
        PredictionItem(
            id="item-1",
            prediction_id=prediction.id,
            item_type="exact_score",
            subject="France vs Brazil",
            value="2-1",
            confidence=0.8,
        ),
        PredictionItem(
            id="item-2",
            prediction_id=prediction.id,
            item_type="match_winner",
            subject="France vs Brazil",
            value="France",
            confidence=0.8,
        ),
    ]
    extracted = ExtractedPredictions(summary=prediction.summary, confidence=prediction.confidence, items=items)

    repository.upsert_team(home_team)
    repository.upsert_team(away_team)
    repository.upsert_match(match)
    repository.upsert_creator(creator)
    repository.upsert_channel(channel)
    repository.upsert_video(video)
    repository.link_video_to_match(match.id, video.id, 0.9)
    repository.save_transcript(transcript)
    repository.save_prediction(prediction, extracted)

    rows = repository.get_matches()

    assert len(rows) == 1
    assert rows[0]["video_count"] == 1
    assert rows[0]["analyzed_video_count"] == 1
    assert rows[0]["predicted_video_count"] == 1
    assert rows[0]["prediction_count"] == 1
    assert rows[0]["predicted_score"] == "2-1"
    assert rows[0]["score_votes"] == 1
