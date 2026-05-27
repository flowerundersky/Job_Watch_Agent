from __future__ import annotations

from pathlib import Path
import sys

from src.config import load_config
from src.workflow import JobWatchWorkflow


DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    config = load_config(Path(arguments[0]) if arguments else DEFAULT_CONFIG_PATH)
    workflow = JobWatchWorkflow(config)
    result = workflow.run()

    print(result.summary)
    print(f"report: {result.report_path}")
    print(f"result: {result.result_path}")
    print(f"snapshot: {result.snapshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
