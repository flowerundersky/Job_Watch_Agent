from __future__ import annotations

from collections.abc import Iterable
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.models import JobPosting


JOB_HINTS = ("job", "career", "position", "recruit", "vacancy", "招聘", "岗位")


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _first_text(node, selectors: Iterable[str]) -> str:
    for selector in selectors:
        found = node.select_one(selector)
        if found:
            text = _normalize_text(found.get_text(" ", strip=True))
            if text:
                return text
    return ""


def _extract_job_from_node(node, source_url: str) -> JobPosting | None:
    title = _normalize_text(node.get("data-title", ""))
    if not title:
        title = _first_text(node, ["h1", "h2", "h3", "a", ".title", ".job-title"])
    if not title:
        return None

    company = _normalize_text(node.get("data-company", "")) or _first_text(node, [".company", ".corp", ".employer"])
    location = _normalize_text(node.get("data-location", "")) or _first_text(node, [".location", ".place", ".city"])
    posted_at = _normalize_text(node.get("data-posted-at", "")) or _first_text(node, ["time", ".date", ".posted-at"])

    anchor = node.find("a", href=True)
    url = urljoin(source_url, anchor["href"]) if anchor else source_url
    description = _normalize_text(node.get_text(" ", strip=True))

    return JobPosting(
        title=unescape(title),
        company=unescape(company),
        location=unescape(location),
        url=url,
        source=source_url,
        posted_at=posted_at,
        description=description,
        metadata={"tag": node.name or "unknown"},
    )


def extract_jobs_from_html(html: str, source_url: str) -> list[JobPosting]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = []

    for node in soup.find_all(True):
        attrs = " ".join(
            [
                node.name or "",
                " ".join(node.get("class", [])),
                node.get("id", ""),
                node.get("role", ""),
                node.get("data-role", ""),
            ]
        ).lower()
        if any(hint in attrs for hint in JOB_HINTS):
            candidates.append(node)

    if not candidates:
        candidates = list(soup.find_all(["article", "li"]))

    jobs: list[JobPosting] = []
    for node in candidates:
        job = _extract_job_from_node(node, source_url)
        if job is not None:
            jobs.append(job)

    if jobs:
        return jobs

    for anchor in soup.find_all("a", href=True):
        title = _normalize_text(anchor.get_text(" ", strip=True))
        if not title:
            continue
        if len(title) > 120:
            continue
        jobs.append(
            JobPosting(
                title=title,
                url=urljoin(source_url, anchor["href"]),
                source=source_url,
                metadata={"tag": "a"},
            )
        )

    return jobs


class JobScraper:
    def __init__(self, timeout_seconds: int = 10, user_agent: str = "JobWatchAgent/0.1") -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def fetch_html(self, url: str) -> str:
        response = requests.get(url, timeout=self.timeout_seconds, headers={"User-Agent": self.user_agent})
        response.raise_for_status()
        return response.text

    def scrape_url(self, url: str) -> list[JobPosting]:
        html = self.fetch_html(url)
        return extract_jobs_from_html(html, url)

    def scrape_urls(self, urls: Iterable[str]) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        for url in urls:
            jobs.extend(self.scrape_url(url))
        return jobs
