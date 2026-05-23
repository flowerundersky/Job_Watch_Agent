from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from src.models import JobPosting


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_snapshot(path: Path, jobs: Iterable[JobPosting]) -> None:
    ensure_parent_dir(path)
    payload = [job.to_dict() for job in jobs]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_snapshot(path: Path) -> list[JobPosting]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [JobPosting.from_dict(item) for item in data]
