from __future__ import annotations

import argparse

from app.config import get_settings
from app.rag.chroma_store import ChromaStore
from app.rag.indexer import index_all_transcripts
from app.services.pipeline import DemoPipeline
from app.utils.logging import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="CDM_INFLUX CLI")
    parser.add_argument("command", choices=["seed", "index-rag"], help="Command to execute")
    args = parser.parse_args()

    setup_logging()
    if args.command == "seed":
        pipeline = DemoPipeline()
        result = pipeline.run()
        print(f"Seeded {result['videos']} videos and {result['prediction_items']} prediction items.")
    elif args.command == "index-rag":
        settings = get_settings()
        pipeline = DemoPipeline(settings=settings)
        pipeline.initialize()
        store = ChromaStore(
            settings.chroma_path,
            ollama_base_url=settings.ollama_base_url,
            embed_model=settings.ollama_embed_model,
        )
        summary = index_all_transcripts(pipeline.repository, store)
        print(
            "Indexed {indexed_videos}/{available_transcripts} transcripts "
            "({indexed_chunks} chunks, {skipped_videos} skipped).".format(**summary)
        )


if __name__ == "__main__":
    main()
