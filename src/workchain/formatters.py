"""Small formatting and payload helpers shared by workflow services."""

from __future__ import annotations

from typing import Any

from ..models import CompanyCandidate, CrawledPage


def status_display(value: str) -> str:
    mapping = {
        "open": "开启",
        "closed": "未开启",
        "unknown": "未知",
    }
    return mapping.get(value.strip().lower(), value or "未知")


def compact_candidate(candidate: CompanyCandidate) -> dict[str, str | int]:
    return {
        "rank": candidate.rank,
        "name": candidate.name,
        "recruitment_url": candidate.recruitment_url,
    }


def compact_page(page: CrawledPage) -> dict[str, Any]:
    return {
        "company": page.company,
        "page_url": page.page_url,
        "recruitment_period": page.recruitment_period,
        "application_start": page.application_start,
        "application_deadline": page.application_deadline,
        "period_evidence": page.period_evidence,
        "date": page.date_candidates[:1],
        "site_type": page.site_type,
        "channel_status": page.channel_status,
        "error": page.error,
    }
