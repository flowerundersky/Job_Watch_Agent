"""Compatibility exports for crawler tools."""

from __future__ import annotations

from .tools.crawler import (
    crawl_company_page,
    crawl_company_pages,
    crawl_url,
    load_company_candidates_from_selection,
    normalize_text,
    resolve_click_target_to_url,
)

__all__ = [
    "crawl_company_page",
    "crawl_company_pages",
    "crawl_url",
    "load_company_candidates_from_selection",
    "normalize_text",
    "resolve_click_target_to_url",
]
