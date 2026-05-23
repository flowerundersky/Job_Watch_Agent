from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any


@dataclass(slots=True)
class JobPosting:
    title: str
    company: str = ""
    location: str = ""
    url: str = ""
    source: str = ""
    posted_at: str = ""
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def stable_key(self) -> tuple[str, str, str]:
        return (
            self.company.strip().lower(),
            self.title.strip().lower(),
            self.location.strip().lower(),
        )

    def content_signature(self) -> str:
        payload = "\n".join(
            [
                self.title.strip(),
                self.company.strip(),
                self.location.strip(),
                self.posted_at.strip(),
                self.url.strip(),
                self.description.strip(),
            ]
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobPosting":
        return cls(**data)


@dataclass(slots=True)
class JobDelta:
    new_jobs: list[JobPosting] = field(default_factory=list)
    changed_jobs: list[JobPosting] = field(default_factory=list)
    removed_jobs: list[JobPosting] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return len(self.new_jobs) + len(self.changed_jobs) + len(self.removed_jobs)


@dataclass(slots=True)
class MatchResult:
    job: JobPosting
    matched: bool
    score: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job": self.job.to_dict(),
            "matched": self.matched,
            "score": self.score,
            "reasons": list(self.reasons),
        }


@dataclass(slots=True)
class RunResult:
    total_jobs: int
    new_jobs: int
    changed_jobs: int
    removed_jobs: int
    matched_jobs: int
    report_path: str
    snapshot_path: str
    summary: str
