"""Crawler helpers for recruitment pages and candidate discovery."""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .models import CompanyCandidate, CrawledPage


SEARCH_URL = "https://html.duckduckgo.com/html/"
SEARCH_HINTS = ("job", "career", "recruit", "work", "招聘", "岗位", "校园招聘")
DATE_PATTERNS = (
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}",
    r"\d{4}年\d{1,2}月\d{1,2}日?",
    r"\d{4}[-/.]\d{1,2}",
    r"\d{1,2}月\d{1,2}日",
)

DEFAULT_COMPANY_FALLBACKS: list[tuple[str, str]] = [
    ("字节跳动", "https://jobs.bytedance.com/"),
    ("腾讯", "https://careers.tencent.com/"),
    ("阿里巴巴", "https://talent.alibaba.com/"),
    ("美团", "https://job.meituan.com/"),
    ("京东", "https://zhaopin.jd.com/"),
    ("百度", "https://talent.baidu.com/"),
    ("华为", "https://career.huawei.com/"),
    ("蚂蚁集团", "https://talent.antgroup.com/"),
    ("拼多多", "https://careers.pinduoduo.com/"),
    ("小红书", "https://job.xiaohongshu.com/"),
]


def normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()


def search_company_candidates(
    job_role: str,
    top_x: int,
    *,
    timeout_seconds: int = 15,
    user_agent: str = "JobWatchAgent/2.0",
) -> list[CompanyCandidate]:
    query = f"{job_role} 招聘 官网"
    try:
        response = requests.get(
            SEARCH_URL,
            params={"q": query},
            timeout=timeout_seconds,
            headers={"User-Agent": user_agent},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        candidates: list[CompanyCandidate] = []
        seen_urls: set[str] = set()
        for index, anchor in enumerate(soup.select("a.result__a"), start=1):
            href = anchor.get("href", "").strip()
            resolved_url = _resolve_search_url(href)
            if not resolved_url or resolved_url in seen_urls:
                continue
            title = normalize_text(anchor.get_text(" ", strip=True))
            if not title:
                continue
            seen_urls.add(resolved_url)
            candidates.append(
                CompanyCandidate(
                    rank=index,
                    name=_derive_company_name(title, resolved_url),
                    recruitment_url=resolved_url,
                    reason=f"搜索结果：{title}",
                    raw={"title": title, "url": resolved_url, "query": query},
                )
            )
            if len(candidates) >= top_x:
                break

        if candidates:
            return candidates
    except Exception:
        pass

    return _fallback_company_candidates(job_role, top_x, query=query)


def crawl_company_pages(
    candidates: list[CompanyCandidate],
    *,
    timeout_seconds: int = 15,
    max_crawl_chars: int = 12000,
    max_links_per_page: int = 20,
    user_agent: str = "JobWatchAgent/2.0",
) -> list[CrawledPage]:
    pages: list[CrawledPage] = []
    for candidate in candidates:
        pages.append(
            crawl_company_page(
                candidate,
                timeout_seconds=timeout_seconds,
                max_crawl_chars=max_crawl_chars,
                max_links_per_page=max_links_per_page,
                user_agent=user_agent,
            )
        )
    return pages


def load_company_candidates_from_selection(path: Path) -> list[CompanyCandidate]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_candidates = _extract_candidates_from_selection_payload(payload)
    candidates: list[CompanyCandidate] = []

    for index, item in enumerate(raw_candidates, start=1):
        if not isinstance(item, dict):
            continue
        name = normalize_text(str(item.get("name") or item.get("company") or ""))
        recruitment_url = normalize_text(
            str(
                item.get("recruitment_url")
                or item.get("url")
                or item.get("career_url")
                or item.get("careers_url")
                or ""
            )
        )
        if not name or not recruitment_url:
            continue
        candidates.append(
            CompanyCandidate(
                rank=int(item.get("rank") or index),
                name=name,
                recruitment_url=recruitment_url,
                reason=str(item.get("reason") or "").strip(),
                raw=item,
            )
        )

    return candidates


def _extract_candidates_from_selection_payload(payload: dict[str, Any]) -> list[Any]:
    for key in ("selected_companies", "candidates", "companies"):
        value = payload.get(key)
        if isinstance(value, list):
            return value

    raw_output = payload.get("raw_selection_output") or payload.get("raw_output")
    if not isinstance(raw_output, str) or not raw_output.strip():
        return []

    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, dict):
        value = parsed.get("companies")
        return value if isinstance(value, list) else []
    return []


def crawl_company_page(
    candidate: CompanyCandidate,
    *,
    timeout_seconds: int = 15,
    max_crawl_chars: int = 12000,
    max_links_per_page: int = 20,
    user_agent: str = "JobWatchAgent/2.0",
) -> CrawledPage:
    try:
        response = requests.get(
            candidate.recruitment_url,
            timeout=timeout_seconds,
            headers={"User-Agent": user_agent},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        title = _extract_title(soup)
        text = normalize_text(soup.get_text("\n", strip=True))[:max_crawl_chars]
        links = _extract_links(soup, response.url, max_links=max_links_per_page)
        date_candidates = _extract_date_candidates(soup, text)
        if not date_candidates:
            date_candidates = _extract_date_candidates_from_links(
                links,
                timeout_seconds=timeout_seconds,
                user_agent=user_agent,
            )
        return CrawledPage(
            company=candidate.name,
            recruitment_url=candidate.recruitment_url,
            page_url=response.url,
            title=title,
            text=text,
            date_candidates=date_candidates,
            links=links,
        )
    except Exception as exc:  # noqa: BLE001
        return CrawledPage(
            company=candidate.name,
            recruitment_url=candidate.recruitment_url,
            page_url=candidate.recruitment_url,
            title="",
            text="",
            date_candidates=[],
            links=[],
            error=str(exc),
        )


def _extract_title(soup: BeautifulSoup) -> str:
    for selector in ("title", "h1", "h2"):
        node = soup.select_one(selector)
        if node:
            text = normalize_text(node.get_text(" ", strip=True))
            if text:
                return unescape(text)
    return ""


def _extract_links(soup: BeautifulSoup, base_url: str, *, max_links: int) -> list[str]:
    links: list[str] = []
    base_domain = urlparse(base_url).netloc
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, anchor["href"])
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"}:
            continue
        if base_domain and parsed.netloc and parsed.netloc != base_domain:
            continue
        if href in links:
            continue
        if not links or any(hint in href.lower() for hint in SEARCH_HINTS):
            links.append(href)
        if len(links) >= max_links:
            break
    return links


def _extract_date_candidates(soup: BeautifulSoup, text: str) -> list[str]:
    candidates: list[str] = []
    for pattern in DATE_PATTERNS:
        for match in re.findall(pattern, text):
            if match not in candidates:
                candidates.append(match)

    for node in soup.find_all("time"):
        value = normalize_text(node.get("datetime", "") or node.get_text(" ", strip=True))
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def _extract_date_candidates_from_links(
    links: list[str],
    *,
    timeout_seconds: int,
    user_agent: str,
) -> list[str]:
    candidates: list[str] = []
    for link in links[:3]:
        try:
            response = requests.get(link, timeout=timeout_seconds, headers={"User-Agent": user_agent})
            response.raise_for_status()
        except Exception:  # noqa: BLE001
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        text = normalize_text(soup.get_text("\n", strip=True))
        for candidate in _extract_date_candidates(soup, text):
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _resolve_search_url(href: str) -> str:
    if not href:
        return ""
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com"):
        params = parse_qs(parsed.query)
        target = params.get("uddg", [""])[0]
        if target:
            return target
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return f"https:{href}"
    return href


def _derive_company_name(title: str, url: str) -> str:
    cleaned = re.sub(r"(?i)(招聘|careers?|jobs?|recruitment|official|官网|校招|社招)", " ", title)
    cleaned = normalize_text(cleaned)
    if cleaned:
        return cleaned[:60]
    domain = urlparse(url).netloc.replace("www.", "")
    return domain.split(".")[0] if domain else title


def _fallback_company_candidates(job_role: str, top_x: int, *, query: str) -> list[CompanyCandidate]:
    matched: list[CompanyCandidate] = []
    role_text = job_role.lower()
    for index, (name, recruitment_url) in enumerate(DEFAULT_COMPANY_FALLBACKS, start=1):
        reason = f"内置兜底：{name} 是常见招聘官网入口，适合继续抓取 {job_role} 相关信息"
        if any(keyword in role_text for keyword in ("前端", "web", "ui", "react", "vue")):
            reason = f"内置兜底：{name} 的技术岗位招聘页适合检索前端相关职位"
        elif any(keyword in role_text for keyword in ("测试", "qa", "质量", "qa")):
            reason = f"内置兜底：{name} 的招聘页适合检索测试与质量保障岗位"
        elif any(keyword in role_text for keyword in ("算法", "ai", "ml", "机器学习", "大模型")):
            reason = f"内置兜底：{name} 的招聘页适合检索算法与 AI 岗位"
        matched.append(
            CompanyCandidate(
                rank=index,
                name=name,
                recruitment_url=recruitment_url,
                reason=reason,
                raw={"query": query, "fallback": True},
            )
        )
        if len(matched) >= top_x:
            break
    return matched
