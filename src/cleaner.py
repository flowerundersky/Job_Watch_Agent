from __future__ import annotations

from collections.abc import Iterable

from src.models import JobPosting


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split()).strip()


def clean_job_posting(job: JobPosting) -> JobPosting:
    return JobPosting(
        title=normalize_whitespace(job.title),
        company=normalize_whitespace(job.company),
        location=normalize_whitespace(job.location),
        url=normalize_whitespace(job.url),
        source=normalize_whitespace(job.source),
        posted_at=normalize_whitespace(job.posted_at),
        description=normalize_whitespace(job.description),
        metadata=dict(job.metadata),
    )


def deduplicate_jobs(jobs: Iterable[JobPosting]) -> list[JobPosting]:
    seen: set[tuple[str, str, str, str]] = set()
    unique_jobs: list[JobPosting] = []
    for job in jobs:
        cleaned = clean_job_posting(job)
        identity = (
            cleaned.company.lower(),
            cleaned.title.lower(),
            cleaned.location.lower(),
            cleaned.url.lower(),
        )
        if identity in seen:
            continue
        seen.add(identity)
        unique_jobs.append(cleaned)
    return unique_jobs
