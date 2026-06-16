"""Snapshot loading and change detection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import AnalysisResult, CrawledPage
from .formatters import compact_page


def build_changes(snapshot_path: Path, crawled_pages: list[CrawledPage], analysis: AnalysisResult) -> dict[str, Any]:
    """和上一次 snapshot 对比，判断时间段、截止日期或通道状态是否变化。"""
    current_snapshot = snapshot_payload(crawled_pages, analysis)
    previous_snapshot = load_previous_snapshot(snapshot_path)
    if not previous_snapshot:
        return {"has_previous": False, "updated": False, "status_changed": False}

    previous_pages = {
        str(item.get("company") or "").strip().lower(): item
        for item in previous_snapshot.get("crawled_pages", [])
        if isinstance(item, dict)
    }
    updated_companies: list[dict[str, Any]] = []
    for page in current_snapshot["crawled_pages"]:
        previous_page = previous_pages.get(str(page.get("company") or "").strip().lower())
        if not previous_page:
            continue
        if (
            page.get("recruitment_period") != previous_page.get("recruitment_period")
            or page.get("application_deadline") != previous_page.get("application_deadline")
            or page.get("channel_status") != previous_page.get("channel_status")
        ):
            updated_companies.append(
                {
                    "company": page.get("company", ""),
                    "previous_period": previous_page.get("recruitment_period", ""),
                    "current_period": page.get("recruitment_period", ""),
                    "previous_deadline": previous_page.get("application_deadline", ""),
                    "current_deadline": page.get("application_deadline", ""),
                    "previous_status": previous_page.get("channel_status", "unknown"),
                    "current_status": page.get("channel_status", "unknown"),
                }
            )

    previous_analysis = previous_snapshot.get("analysis", {})
    period_changed = previous_analysis.get("recruitment_period") != analysis.recruitment_period
    deadline_changed = previous_analysis.get("application_deadline") != analysis.application_deadline
    status_changed = previous_snapshot.get("analysis", {}).get("channel_status") != analysis.channel_status
    return {
        "has_previous": True,
        "updated": bool(updated_companies or period_changed or deadline_changed),
        "status_changed": status_changed,
        "latest_changed": period_changed or deadline_changed,
        "period_changed": period_changed,
        "deadline_changed": deadline_changed,
        "updated_companies": updated_companies,
    }


def snapshot_payload(crawled_pages: list[CrawledPage], analysis: AnalysisResult) -> dict[str, Any]:
    return {
        "job_role": analysis.job_role,
        "selected_companies": [],
        "crawled_pages": [compact_page(page) for page in crawled_pages],
        "analysis": {
            "job_role": analysis.job_role,
            "period_company": analysis.period_company,
            "recruitment_period": analysis.recruitment_period,
            "application_start": analysis.application_start,
            "application_deadline": analysis.application_deadline,
            "period_evidence": analysis.period_evidence,
            "latest_company": analysis.latest_company,
            "latest_posted_at": analysis.latest_posted_at,
            "channel_status": analysis.channel_status,
            "confidence": analysis.confidence,
        },
    }


def load_previous_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}
