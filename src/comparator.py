from __future__ import annotations

from collections.abc import Iterable

from src.models import JobDelta, JobPosting


def compare_job_snapshots(
    previous_jobs: Iterable[JobPosting],
    current_jobs: Iterable[JobPosting],
) -> JobDelta:
    previous_map = {job.stable_key(): job for job in previous_jobs}
    current_map = {job.stable_key(): job for job in current_jobs}

    new_jobs: list[JobPosting] = []
    changed_jobs: list[JobPosting] = []
    removed_jobs: list[JobPosting] = []

    for key, job in current_map.items():
        old_job = previous_map.get(key)
        if old_job is None:
            new_jobs.append(job)
        elif old_job.content_signature() != job.content_signature():
            changed_jobs.append(job)

    for key, job in previous_map.items():
        if key not in current_map:
            removed_jobs.append(job)

    return JobDelta(new_jobs=new_jobs, changed_jobs=changed_jobs, removed_jobs=removed_jobs)
