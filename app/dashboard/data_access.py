from __future__ import annotations

from app.services.pipeline import bootstrap_demo_environment
from app.services.ranking import rank_predictions


def get_dashboard_repository():
    return bootstrap_demo_environment()


def get_ranked_consensus(repository) -> list[dict]:
    comparison_rows = repository.get_creator_comparison()
    ranking_input = [
        {
            "subject": row["subject"],
            "value": row["value"],
            "confidence": row["confidence"],
            "creator_name": row["creator_name"],
            "creator_weight": 1.0,
            "historical_accuracy": 0.5,
        }
        for row in comparison_rows
        if row["item_type"] in {"match_winner", "exact_score", "tournament_winner"}
    ]
    return rank_predictions(ranking_input)


def fetch_videos_for_match(match_id: str, max_results: int = 5) -> int:
    from app.services.match_ingestion import MatchIngestionPipeline
    pipeline = MatchIngestionPipeline()
    pipeline.database.initialize()
    return pipeline.fetch_videos_for_match(match_id, max_results)


def analyze_match_videos(match_id: str, video_ids: list[str] | None = None) -> dict[str, int]:
    from app.services.match_ingestion import MatchIngestionPipeline
    pipeline = MatchIngestionPipeline()
    pipeline.database.initialize()
    return pipeline.analyze_match_videos(match_id, video_ids)
