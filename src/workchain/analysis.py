"""Analysis helpers for combining page-agent outputs."""

from __future__ import annotations

from ..models import AnalysisResult, CompanyCandidate, CrawledPage
from .formatters import status_display


def combine_agent_results(job_role: str, date_pages: list[CrawledPage], channel_pages: list[CrawledPage]) -> AnalysisResult:
    """从页面探索结果中选出最可信的招聘时间段和通道状态。"""
    period_company = ""
    recruitment_period = ""
    application_start = ""
    application_deadline = ""
    period_evidence = ""
    period_confidence = "low"
    for page in date_pages:
        if (page.recruitment_period or page.application_deadline or page.application_start) and not (
            recruitment_period or application_deadline or application_start
        ):
            period_company = page.company
            recruitment_period = page.recruitment_period
            application_start = page.application_start
            application_deadline = page.application_deadline
            period_evidence = page.period_evidence
            period_confidence = page.decision_confidence or "low"
    if not period_company and date_pages:
        period_company = date_pages[0].company

    channel_status = "unknown"
    channel_confidence = "low"
    for page in channel_pages:
        if page.channel_status in {"open", "closed"}:
            channel_status = page.channel_status
            channel_confidence = page.decision_confidence or "high"
            break

    confidence = period_confidence if period_confidence != "low" else channel_confidence
    return AnalysisResult(
        job_role=job_role,
        period_company=period_company,
        recruitment_period=recruitment_period,
        application_start=application_start,
        application_deadline=application_deadline,
        period_evidence=period_evidence,
        latest_company=period_company,
        latest_posted_at=recruitment_period or application_deadline or application_start,
        channel_status=channel_status,
        confidence=confidence,
    )


def build_summary(
    job_role: str,
    selected_candidates: list[CompanyCandidate],
    crawled_pages: list[CrawledPage],
    analysis: AnalysisResult,
) -> str:
    return (
        f"job={job_role}; companies={len(selected_candidates)}; "
        f"period={analysis.recruitment_period or analysis.application_deadline or '未识别'}; "
        f"status={status_display(analysis.channel_status)}"
    )
