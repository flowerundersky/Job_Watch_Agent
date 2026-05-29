from __future__ import annotations

from pathlib import Path
import sys

from src.config import load_config
from src.workflow import JobWatchWorkflow


DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")


def main(argv: list[str] | None = None) -> int:
    
    config = load_config(DEFAULT_CONFIG_PATH)

    workflow = JobWatchWorkflow(config)
    result = workflow.run()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
