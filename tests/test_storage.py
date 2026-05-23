from pathlib import Path

from src.models import JobPosting
from src.storage import load_snapshot, save_snapshot


def test_snapshot_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    jobs = [
        JobPosting(title="Python Engineer", company="Example Co", location="Shanghai"),
        JobPosting(title="Data Analyst", company="Example Co", location="Beijing"),
    ]

    save_snapshot(path, jobs)
    loaded_jobs = load_snapshot(path)

    assert loaded_jobs == jobs
