from __future__ import annotations

from pathlib import Path
import sys

from src.config import load_config
from src.pipeline import JobMonitorPipeline


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    config_path = Path(arguments[0]) if arguments else Path("config.yaml")

    config = load_config(config_path)
    pipeline = JobMonitorPipeline(config)
    result = pipeline.run()

    print(result.summary)
    print(f"report: {result.report_path}")
    print(f"snapshot: {result.snapshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
