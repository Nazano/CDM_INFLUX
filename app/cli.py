from __future__ import annotations

import argparse

from app.services.pipeline import DemoPipeline
from app.utils.logging import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="CDM_INFLUX CLI")
    parser.add_argument("command", choices=["seed"], help="Command to execute")
    args = parser.parse_args()

    setup_logging()
    if args.command == "seed":
        pipeline = DemoPipeline()
        result = pipeline.run()
        print(f"Seeded {result['videos']} videos and {result['prediction_items']} prediction items.")


if __name__ == "__main__":
    main()
