"""Crawler helpers for recruitment pages and candidate discovery."""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

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

API_HINTS = ("api", "json", "graphql", "xhr", "fetch", "ajax", "data-")
CHANNEL_OPEN_HINTS = ("校招进行中", "校招开启", "校园招聘", "招聘中", "正在招聘", "开放投递", "开启投递")
CHANNEL_CLOSED_HINTS = ("已结束", "停止招聘", "暂未开放", "未开启", "暂停招聘", "已关闭", "招聘结束")
CAREER_URL_HINTS = (
    "career",
    "careers",
    "job",
    "jobs",
    "talent",
    "recruit",
    "recruitment",
    "zhaopin",
    "campus",
    "campus-recruit",
    "school-recruit",
    "graduate",
    "campus招聘",
    "校招",
    "招聘",
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
    company_filters: str = "",
    timeout_seconds: int = 15,
    user_agent: str = "JobWatchAgent/2.0",
) -> list[CompanyCandidate]:
    filter_text = company_filters.strip()
    query = f"{job_role} 招聘 官网"
    if filter_text:
        query = f"{query} {filter_text}"
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
            if not _looks_like_campus_recruitment_url(resolved_url):
                continue
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

    return _fallback_company_candidates(job_role, top_x, query=query, company_filters=filter_text)


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


def crawl_url(
    company: str,
    recruitment_url: str,
    *,
    timeout_seconds: int = 15,
    max_crawl_chars: int = 12000,
    max_links_per_page: int = 20,
    user_agent: str = "JobWatchAgent/2.0",
) -> CrawledPage:
    try:
        rendered = _render_page_with_playwright(
            recruitment_url,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
            max_links=max_links_per_page,
        )
        html = str(rendered.get("html", ""))
        final_url = str(rendered.get("url") or recruitment_url)
        soup = BeautifulSoup(html, "html.parser")
        title = str(rendered.get("title") or _extract_title(soup))
        text = normalize_text(str(rendered.get("visible_text") or soup.get_text("\n", strip=True)))[:max_crawl_chars]
        links = _merge_links(
            rendered.get("links", []),
            _extract_links(soup, final_url, max_links=max_links_per_page),
            max_links=max_links_per_page,
        )
        date_candidates = _extract_date_candidates(soup, text)
        channel_status = _extract_channel_status(text, date_candidates)
        observation = _build_page_observation(
            soup,
            page_url=final_url,
            title=title,
            visible_text=text,
            links=links,
            browser_elements=rendered.get("elements", []),
            max_links=max_links_per_page,
        )
        return CrawledPage(
            company=company,
            recruitment_url=recruitment_url,
            page_url=final_url,
            site_type="playwright",
            channel_status=channel_status,
            title=title,
            text=text,
            date_candidates=date_candidates,
            links=links,
            observation=observation,
        )
    except Exception as exc:  # noqa: BLE001
        return CrawledPage(
            company=company,
            recruitment_url=recruitment_url,
            page_url=recruitment_url,
            site_type="playwright",
            channel_status="unknown",
            title="",
            text="",
            date_candidates=[],
            links=[],
            observation={},
            error=str(exc),
        )


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
    selection = payload.get("selection")
    if isinstance(selection, dict):
        value = selection.get("selected_companies")
        if isinstance(value, list):
            return value
    for key in ("selected", "selected_companies", "candidates", "companies"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _looks_like_campus_recruitment_url(url: str) -> bool:
    normalized = unquote(url).lower()
    parsed = urlparse(normalized)
    target = f"{parsed.netloc}{parsed.path}"
    return any(hint in target for hint in CAREER_URL_HINTS)


def crawl_company_page(
    candidate: CompanyCandidate,
    *,
    timeout_seconds: int = 15,
    max_crawl_chars: int = 12000,
    max_links_per_page: int = 20,
    user_agent: str = "JobWatchAgent/2.0",
) -> CrawledPage:
    return crawl_url(
        candidate.name,
        candidate.recruitment_url,
        timeout_seconds=timeout_seconds,
        max_crawl_chars=max_crawl_chars,
        max_links_per_page=max_links_per_page,
        user_agent=user_agent,
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


def _extract_date_candidates_from_api(
    links: list[str],
    *,
    timeout_seconds: int,
    user_agent: str,
) -> list[str]:
    candidates: list[str] = []
    for link in _extract_api_urls(links)[:3]:
        try:
            response = requests.get(link, timeout=timeout_seconds, headers={"User-Agent": user_agent})
            response.raise_for_status()
            payload = response.json()
        except Exception:  # noqa: BLE001
            continue
        text = normalize_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        for candidate in _extract_date_candidates_from_text(text):
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _extract_api_urls(links: list[str]) -> list[str]:
    api_urls: list[str] = []
    for link in links:
        lowered = link.lower()
        if any(hint in lowered for hint in API_HINTS) and link not in api_urls:
            api_urls.append(link)
    return api_urls


def _extract_date_candidates_from_text(text: str) -> list[str]:
    candidates: list[str] = []
    for pattern in DATE_PATTERNS:
        for match in re.findall(pattern, text):
            if match not in candidates:
                candidates.append(match)
    return candidates


def _probe_api_urls(soup: BeautifulSoup, base_url: str, html: str) -> list[str]:
    api_urls: list[str] = []

    def _append(raw_url: str) -> None:
        if not raw_url:
            return
        resolved = urljoin(base_url, raw_url.strip())
        if _looks_like_api_endpoint(resolved) and resolved not in api_urls:
            api_urls.append(resolved)

    for tag in soup.find_all(True):
        for attr in ("href", "src", "data-url", "data-api", "data-endpoint", "data-fetch-url", "data-json"):
            value = tag.get(attr)
            if isinstance(value, str):
                _append(value)

    for match in re.findall(r"https?://[^\"'\s<>]+", html):
        _append(match)

    return api_urls


def _looks_like_api_endpoint(url: str) -> bool:
    parsed = urlparse(url)
    target = f"{parsed.netloc}{parsed.path}{parsed.query}".lower()
    return any(hint in target for hint in API_HINTS)


def _detect_site_type(soup: BeautifulSoup, text: str, links: list[str]) -> str:
    if any(any(hint in link.lower() for hint in API_HINTS) for link in links):
        return "api"
    if len(text) < 80 and soup.find_all("script"):
        return "playwright"
    return "html"


def _extract_channel_status(text: str, date_candidates: list[str]) -> str:
    compact = normalize_text(text)
    if any(hint in compact for hint in CHANNEL_CLOSED_HINTS):
        return "closed"
    if any(hint in compact for hint in CHANNEL_OPEN_HINTS):
        return "open"
    if date_candidates and any(keyword in compact for keyword in ("校招", "校园招聘", "招聘")):
        return "open"
    return "unknown"


def _render_page_with_playwright(
    url: str,
    *,
    timeout_seconds: int,
    user_agent: str,
    max_links: int,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Playwright is not available") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(user_agent=user_agent)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_seconds * 1000, 8000))
            except Exception:  # noqa: BLE001
                pass
            html = page.content()
            visible_text = page.locator("body").inner_text(timeout=3000) if page.locator("body").count() else ""
            elements = page.evaluate(
                """
                (limit) => Array.from(
                  document.querySelectorAll('a,button,[role="button"],input[type="button"],input[type="submit"]')
                ).slice(0, limit).map((el) => {
                  const rect = el.getBoundingClientRect();
                  const style = window.getComputedStyle(el);
                  return {
                    tag: el.tagName.toLowerCase(),
                    role: el.getAttribute('role') || '',
                    text: (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').trim(),
                    href: el.href || el.getAttribute('href') || '',
                    visible: !!(rect.width || rect.height) && style.visibility !== 'hidden' && style.display !== 'none'
                  };
                }).filter((item) => item.text || item.href)
                """,
                max_links * 2,
            )
            links = [
                str(item.get("href", "")).strip()
                for item in elements
                if isinstance(item, dict) and str(item.get("href", "")).strip()
            ]
            return {
                "url": page.url,
                "title": page.title(),
                "html": html,
                "visible_text": visible_text,
                "links": links[:max_links],
                "elements": elements,
            }
        finally:
            browser.close()


def _render_with_playwright(url: str, *, timeout_seconds: int, user_agent: str) -> str:
    try:
        rendered = _render_page_with_playwright(
            url,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
            max_links=20,
        )
    except Exception:  # noqa: BLE001
        return ""
    return str(rendered.get("html", ""))


def _merge_links(primary: Any, secondary: list[str], *, max_links: int) -> list[str]:
    links: list[str] = []
    for raw_link in [*list(primary or []), *secondary]:
        link = str(raw_link).strip()
        if link and link not in links:
            links.append(link)
        if len(links) >= max_links:
            break
    return links


def _build_page_observation(
    soup: BeautifulSoup,
    *,
    page_url: str,
    title: str,
    visible_text: str,
    links: list[str],
    browser_elements: Any,
    max_links: int,
) -> dict[str, Any]:
    headings = _collect_headings(soup)
    elements = _normalize_browser_elements(browser_elements, max_items=max_links * 2)
    return {
        "page_url": page_url,
        "title": title,
        "headings": headings[:20],
        "visible_text_excerpt": visible_text[:1200],
        "sections": _collect_section_observations(soup, page_url, max_sections=12, max_links_per_section=6),
        "interactive_elements": elements,
        "links": links[:max_links],
    }


def _collect_headings(soup: BeautifulSoup) -> list[str]:
    headings: list[str] = []
    for node in soup.select("h1,h2,h3,h4,[role='heading']"):
        text = normalize_text(node.get_text(" ", strip=True))
        if text and text not in headings:
            headings.append(text)
    return headings


def _collect_section_observations(
    soup: BeautifulSoup,
    page_url: str,
    *,
    max_sections: int,
    max_links_per_section: int,
) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    candidates = soup.select("main,section,article,nav,header,footer")
    if not candidates:
        candidates = soup.select("div")

    for node in candidates:
        text = normalize_text(node.get_text(" ", strip=True))
        if len(text) < 20:
            continue
        heading_node = node.select_one("h1,h2,h3,h4,[role='heading']")
        heading = normalize_text(heading_node.get_text(" ", strip=True)) if heading_node else ""
        section_links = []
        for anchor in node.find_all("a", href=True):
            label = normalize_text(anchor.get_text(" ", strip=True) or anchor.get("aria-label", "") or anchor.get("title", ""))
            href = urljoin(page_url, anchor["href"])
            if not label and not href:
                continue
            item = {"text": label, "href": href}
            if item not in section_links:
                section_links.append(item)
            if len(section_links) >= max_links_per_section:
                break
        sections.append(
            {
                "heading": heading,
                "text": text[:600],
                "links": section_links,
            }
        )
        if len(sections) >= max_sections:
            break
    return sections


def _normalize_browser_elements(elements: Any, *, max_items: int) -> list[dict[str, Any]]:
    if not isinstance(elements, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in elements:
        if not isinstance(item, dict):
            continue
        text = normalize_text(str(item.get("text", "")))
        href = str(item.get("href", "")).strip()
        if not text and not href:
            continue
        normalized.append(
            {
                "tag": str(item.get("tag", "")),
                "role": str(item.get("role", "")),
                "text": text[:120],
                "href": href,
                "visible": bool(item.get("visible")),
            }
        )
        if len(normalized) >= max_items:
            break
    return normalized


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


def _fallback_company_candidates(
    job_role: str,
    top_x: int,
    *,
    query: str,
    company_filters: str = "",
) -> list[CompanyCandidate]:
    matched: list[CompanyCandidate] = []
    role_text = job_role.lower()
    filter_text = company_filters.lower()
    for index, (name, recruitment_url) in enumerate(DEFAULT_COMPANY_FALLBACKS, start=1):
        reason = f"内置兜底：{name} 是常见招聘官网入口，适合继续抓取 {job_role} 相关信息"
        if filter_text:
            reason = f"内置兜底：{name} 适合继续抓取 {job_role}，并满足筛选条件：{company_filters}"
        if any(keyword in role_text for keyword in ("前端", "web", "ui", "react", "vue")):
            reason = f"内置兜底：{name} 的技术岗位招聘页适合检索前端相关职位"
        elif any(keyword in role_text for keyword in ("测试", "qa", "质量", "qa")):
            reason = f"内置兜底：{name} 的招聘页适合检索测试与质量保障岗位"
        elif any(keyword in role_text for keyword in ("算法", "ai", "ml", "机器学习", "大模型")):
            reason = f"内置兜底：{name} 的招聘页适合检索算法与 AI 岗位"
        if filter_text:
            reason = f"{reason}；筛选条件：{company_filters}"
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
