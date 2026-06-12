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


def run_analysis_pipeline(
    match_id: str,
    *,
    max_results: int = 5,
    video_ids: list[str] | None = None,
    step_filter: str | None = None,
    progress_callback=None,
    note: str | None = None,
) -> dict:
    from app.services.match_ingestion import MatchIngestionPipeline

    pipeline = MatchIngestionPipeline()
    pipeline.database.initialize()
    return pipeline.run_match_pipeline(
        match_id,
        max_results_per_query=max_results,
        video_ids=video_ids,
        step_filter=step_filter,
        progress_callback=progress_callback,
        note=note,
    )


def schedule_analysis_run(match_id: str, scheduled_for, note: str | None = None) -> str:
    from app.services.match_ingestion import MatchIngestionPipeline

    pipeline = MatchIngestionPipeline()
    pipeline.database.initialize()
    return pipeline.schedule_match_analysis(match_id, scheduled_for=scheduled_for, note=note)


def run_queued_analysis(run_id: str, progress_callback=None) -> dict:
    from app.services.match_ingestion import MatchIngestionPipeline

    pipeline = MatchIngestionPipeline()
    pipeline.database.initialize()
    return pipeline.run_queued_analysis(run_id, progress_callback=progress_callback)
