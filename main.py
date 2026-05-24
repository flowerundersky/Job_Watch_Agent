from __future__ import annotations

from pathlib import Path
import sys

from src.config import load_config
from src.workflow import JobWatchWorkflow


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    config_path = Path(arguments[0]) if arguments else Path("config.yaml")

    config = load_config(config_path)
    workflow = JobWatchWorkflow(config)
    result = workflow.run()

    print(result.summary)
    print(f"report: {result.report_path}")
    print(f"result: {result.result_path}")
    print(f"snapshot: {result.snapshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
