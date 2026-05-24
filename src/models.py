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
    title: str
    text: str
    date_candidates: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AnalysisResult:
    job_role: str
    latest_company: str
    latest_posted_at: str
    evidence: str
    summary: str
    confidence: str
    raw_output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkflowResult:
    job_role: str
    top_x: int
    selected_companies: list[CompanyCandidate]
    crawled_pages: list[CrawledPage]
    analysis: AnalysisResult
    raw_selection_output: str
    raw_analysis_output: str
    report_path: str
    result_path: str
    snapshot_path: str
    summary: str
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_role": self.job_role,
            "top_x": self.top_x,
            "selected_companies": [item.to_dict() for item in self.selected_companies],
            "crawled_pages": [item.to_dict() for item in self.crawled_pages],
            "analysis": self.analysis.to_dict(),
            "raw_selection_output": self.raw_selection_output,
            "raw_analysis_output": self.raw_analysis_output,
            "report_path": self.report_path,
            "result_path": self.result_path,
            "snapshot_path": self.snapshot_path,
            "summary": self.summary,
            "error": self.error,
        }
