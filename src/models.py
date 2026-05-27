from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class CompanyCandidate:
    rank: int
    name: str
    recruitment_url: str
    reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CrawledPage:
    company: str
    recruitment_url: str
    page_url: str
    task_type: str = ""
    site_type: str = "html"
    channel_status: str = "unknown"
    latest_posted_at: str = ""
    decision_confidence: str = "low"
    is_sufficient: bool = False
    title: str = ""
    text: str = ""
    date_candidates: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    next_hops: list[str] = field(default_factory=list)
    visited_urls: list[str] = field(default_factory=list)
    decision_reason: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AnalysisResult:
    job_role: str
    latest_company: str
    latest_posted_at: str
    channel_status: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkflowResult:
    job_role: str
    top_x: int
    selected_companies: list[CompanyCandidate]
    crawled_pages: list[CrawledPage]
    analysis: AnalysisResult
    report_path: str
    result_path: str
    snapshot_path: str
    summary: str
    changes: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    missing_companies: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_role": self.job_role,
            "top_x": self.top_x,
            "selected_companies": [item.to_dict() for item in self.selected_companies],
            "missing_companies": self.missing_companies,
            "crawled_pages": [item.to_dict() for item in self.crawled_pages],
            "analysis": self.analysis.to_dict(),
            "report_path": self.report_path,
            "result_path": self.result_path,
            "snapshot_path": self.snapshot_path,
            "summary": self.summary,
            "changes": self.changes,
            "error": self.error,
        }
