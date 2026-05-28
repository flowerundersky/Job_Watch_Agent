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
NAVIGATION_CLICK_HINTS = (
    "校园招聘",
    "校招",
    "实习",
    "实习就业",
    "招聘动态",
    "招聘公告",
    "招聘项目",
    "职位",
    "岗位",
    "查看岗位",
    "投递",
    "网申",
    "应届生",
    "毕业生",
)
ACTION_CLICK_HINTS = (
    "报名",
    "投递",
    "申请",
    "查看",
    "职位",
    "岗位",
    "详情",
    "了解",
    "进入",
    "加入",
    "立即",
    "点我",
    "去投递",
    "查看岗位",
    "查看职位",
    "报名入口",
)
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
    browser_name: str = "firefox",
    render_retries: int = 2,
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
                browser_name=browser_name,
                render_retries=render_retries,
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
    browser_name: str = "firefox",
    render_retries: int = 2,
    max_crawl_chars: int = 12000,
    max_links_per_page: int = 20,
    user_agent: str = "JobWatchAgent/2.0",
) -> CrawledPage:
    try:
        rendered = _render_page_with_playwright(
            recruitment_url,
            timeout_seconds=timeout_seconds,
            browser_name=browser_name,
            render_retries=render_retries,
            user_agent=user_agent,
            max_links=max_links_per_page,
        )
        html = str(rendered.get("html", ""))
        final_url = str(rendered.get("url") or recruitment_url)
        soup = BeautifulSoup(html, "html.parser")
        title = str(rendered.get("title") or _extract_title(soup))
        text = normalize_text(str(rendered.get("visible_text") or soup.get_text("\n", strip=True)))[:max_crawl_chars]
        links: list[str] = []
        date_candidates = _extract_date_candidates(soup, text)
        channel_status = _extract_channel_status(text, date_candidates)
        observation = _build_page_observation(
            soup,
            page_url=final_url,
            title=title,
            visible_text=text,
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


def resolve_click_target_to_url(
    url: str,
    target: dict[str, str],
    choose_hover_target: Any,
    *,
    timeout_seconds: int = 15,
    browser_name: str = "firefox",
    render_retries: int = 2,
    user_agent: str = "JobWatchAgent/2.0",
) -> dict[str, Any]:
    if not _is_navigable_http_url(url) or not str(target.get("text", "")).strip():
        return {"url": "", "chain": []}
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        return {"url": "", "chain": []}

    with sync_playwright() as playwright:
        for candidate_browser in _browser_attempt_order(browser_name):
            launcher = getattr(playwright, candidate_browser)
            for _ in range(max(1, render_retries + 1)):
                browser = launcher.launch(headless=True)
                page = browser.new_page(
                    user_agent=user_agent,
                    viewport={"width": 1366, "height": 900},
                    locale="zh-CN",
                )
                try:
                    page.set_default_timeout(timeout_seconds * 1000)
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=min(timeout_seconds * 1000, 8000))
                    except Exception:  # noqa: BLE001
                        pass
                    result = _resolve_click_target_on_page(page, target, choose_hover_target, max_depth=3)
                    if result.get("url"):
                        return result
                except Exception:  # noqa: BLE001
                    pass
                finally:
                    browser.close()
    return {"url": "", "chain": []}


def click_menu_to_url(
    url: str,
    menu_text: str,
    *,
    timeout_seconds: int = 15,
    browser_name: str = "firefox",
    render_retries: int = 2,
    user_agent: str = "JobWatchAgent/2.0",
) -> str:
    result = resolve_click_target_to_url(
        url,
        {"type": "menu", "text": menu_text},
        lambda _parent, _targets: {},
        timeout_seconds=timeout_seconds,
        browser_name=browser_name,
        render_retries=render_retries,
        user_agent=user_agent,
    )
    return str(result.get("url", ""))


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
    browser_name: str = "firefox",
    render_retries: int = 2,
    max_crawl_chars: int = 12000,
    max_links_per_page: int = 20,
    user_agent: str = "JobWatchAgent/2.0",
) -> CrawledPage:
    return crawl_url(
        candidate.name,
        candidate.recruitment_url,
        timeout_seconds=timeout_seconds,
        browser_name=browser_name,
        render_retries=render_retries,
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
    browser_name: str,
    render_retries: int,
    user_agent: str,
    max_links: int,
) -> dict[str, Any]:
    if not _is_navigable_http_url(url):
        raise ValueError(f"URL is not navigable: {url}")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Playwright is not available") from exc

    with sync_playwright() as playwright:
        errors: list[str] = []
        for candidate_browser in _browser_attempt_order(browser_name):
            launcher = getattr(playwright, candidate_browser)
            for attempt in range(max(1, render_retries + 1)):
                browser = launcher.launch(headless=True)
                page = browser.new_page(
                    user_agent=user_agent,
                    viewport={"width": 1366, "height": 900},
                    locale="zh-CN",
                )
                try:
                    page.set_default_timeout(timeout_seconds * 1000)
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
                    try:
                        page.wait_for_load_state("load", timeout=min(timeout_seconds * 1000, 10000))
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        page.wait_for_load_state("networkidle", timeout=min(timeout_seconds * 1000, 8000))
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(1200)
                    html = page.content()
                    visible_text = page.locator("body").inner_text(timeout=3000) if page.locator("body").count() else ""
                    elements = page.evaluate(
                        """
                        (limit) => Array.from(
                          document.querySelectorAll('a,button,[role="button"],input[type="button"],input[type="submit"]')
                        ).slice(0, limit).map((el) => {
                          const rect = el.getBoundingClientRect();
                          const style = window.getComputedStyle(el);
                          const inNavigation = !!el.closest('header,nav,[role="navigation"],.nav,.navbar,.menu,.header');
                          return {
                            tag: el.tagName.toLowerCase(),
                            role: el.getAttribute('role') || '',
                            text: (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').trim(),
                            href: el.href || el.getAttribute('href') || '',
                            visible: !!(rect.width || rect.height) && style.visibility !== 'hidden' && style.display !== 'none',
                            top: Math.round(rect.top),
                            left: Math.round(rect.left),
                            in_navigation: inNavigation || rect.top < 140
                          };
                        }).filter((item) => item.text || item.href)
                        """,
                        max_links * 4,
                    )
                    result = {
                        "url": page.url,
                        "title": page.title(),
                        "html": html,
                        "visible_text": visible_text,
                        "links": [],
                        "elements": elements,
                    }
                    _raise_if_blank_render(result)
                    return result
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{candidate_browser} attempt {attempt + 1}: {exc}")
                finally:
                    browser.close()
        raise RuntimeError("; ".join(errors) or f"Failed to render {url}")


def _render_with_playwright(url: str, *, timeout_seconds: int, user_agent: str) -> str:
    try:
        rendered = _render_page_with_playwright(
            url,
            timeout_seconds=timeout_seconds,
            browser_name="firefox",
            render_retries=2,
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
        if _is_navigable_http_url(link) and link not in links:
            links.append(link)
        if len(links) >= max_links:
            break
    return links


def _looks_like_navigation_click(text: str) -> bool:
    if not text or len(text) > 30:
        return False
    if text in {"首页", "登录", "个人中心", "关于我们", "了解百度", "生活在腾讯", "产品和服务", "工作地点"}:
        return False
    return any(hint in text for hint in NAVIGATION_CLICK_HINTS)


def _looks_like_action_click(text: str) -> bool:
    if not text or len(text) > 40:
        return False
    return any(hint in text for hint in ACTION_CLICK_HINTS)


def _browser_attempt_order(browser_name: str) -> list[str]:
    preferred = browser_name.strip().lower() or "firefox"
    if preferred not in {"firefox", "chromium", "webkit"}:
        preferred = "firefox"
    order = [preferred]
    for fallback in ("chromium", "firefox"):
        if fallback not in order:
            order.append(fallback)
    return order


def _is_navigable_http_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _raise_if_blank_render(rendered: dict[str, Any]) -> None:
    page_url = str(rendered.get("url") or "")
    title = normalize_text(str(rendered.get("title") or ""))
    visible_text = normalize_text(str(rendered.get("visible_text") or ""))
    links = rendered.get("links") or []
    if page_url == "about:blank":
        raise RuntimeError("browser stayed on about:blank")
    if not title and not visible_text and not links:
        raise RuntimeError("rendered page is blank")


def _build_page_observation(
    soup: BeautifulSoup,
    *,
    page_url: str,
    title: str,
    visible_text: str,
    browser_elements: Any,
    max_links: int,
) -> dict[str, Any]:
    headings = _collect_headings(soup)
    elements = _normalize_browser_elements(browser_elements, max_items=max_links * 2)
    menus = _extract_navigation_elements(elements, max_items=max_links)
    actions = _extract_action_elements(elements, max_items=max_links)
    return {
        "page_url": page_url,
        "title": title,
        "headings": headings[:20],
        "content": visible_text[:1200],
        "sections": _collect_section_observations(soup, page_url, max_sections=12),
        "menus": menus,
        "actions": actions,
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
        sections.append(
            {
                "heading": heading,
                "text": text[:600],
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
        if not text:
            continue
        normalized.append(
            {
                "tag": str(item.get("tag", "")),
                "role": str(item.get("role", "")),
                "text": text[:120],
                "visible": bool(item.get("visible")),
                "top": item.get("top"),
                "left": item.get("left"),
                "in_navigation": bool(item.get("in_navigation")),
            }
        )
        if len(normalized) >= max_items:
            break
    return normalized


def _extract_navigation_elements(elements: list[dict[str, Any]], *, max_items: int) -> list[dict[str, Any]]:
    navigation_elements: list[dict[str, Any]] = []
    for item in elements:
        if not isinstance(item, dict) or not item.get("visible"):
            continue
        text = normalize_text(str(item.get("text", "")))
        if not text:
            continue
        if not item.get("in_navigation") and not _looks_like_navigation_click(text):
            continue
        navigation_elements.append(
            {
                "text": text[:120],
                "tag": str(item.get("tag", "")),
                "top": item.get("top"),
                "left": item.get("left"),
                "click_candidate": _looks_like_navigation_click(text),
            }
        )
        if len(navigation_elements) >= max_items:
            break
    return navigation_elements


def _extract_action_elements(elements: list[dict[str, Any]], *, max_items: int) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for item in elements:
        if not isinstance(item, dict) or not item.get("visible") or item.get("in_navigation"):
            continue
        text = normalize_text(str(item.get("text", "")))
        if not _looks_like_action_click(text):
            continue
        actions.append(
            {
                "text": text[:120],
                "tag": str(item.get("tag", "")),
                "top": item.get("top"),
                "left": item.get("left"),
                "click_candidate": True,
            }
        )
        if len(actions) >= max_items:
            break
    return actions


def _resolve_click_target_on_page(page: Any, target: dict[str, str], choose_hover_target: Any, *, max_depth: int) -> dict[str, Any]:
    current = _normalize_target_dict(target)
    chain: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for depth in range(max_depth):
        if not current.get("text"):
            return {"url": "", "chain": chain}
        key = (current.get("type", ""), current.get("text", ""))
        if key in seen:
            break
        seen.add(key)
        before_targets = _extract_click_targets_from_page(page)
        before_texts = {item["text"] for item in before_targets if item.get("text")}
        hover_targets = _hover_target_and_collect(page, current, before_texts)
        step = {
            "depth": depth + 1,
            "target": current,
            "hover_targets": hover_targets,
        }
        if hover_targets:
            chosen = _normalize_target_dict(choose_hover_target(current, hover_targets))
            step["chosen_hover_target"] = chosen
            chain.append(step)
            if chosen.get("text"):
                current = chosen
                continue
            current = hover_targets[0]
            continue
        before_url = page.url
        _click_target_text(page, current.get("text", ""))
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:  # noqa: BLE001
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1000)
        after_url = page.url
        step["clicked_url"] = after_url if after_url != before_url else ""
        chain.append(step)
        return {"url": after_url if _is_navigable_http_url(after_url) and after_url != before_url else "", "chain": chain}
    return {"url": "", "chain": chain}


def _hover_target_and_collect(page: Any, target: dict[str, str], before_texts: set[str]) -> list[dict[str, str]]:
    try:
        locator = _target_locator(page, target.get("text", ""))
        locator.hover(timeout=2500)
        page.wait_for_timeout(700)
    except Exception:  # noqa: BLE001
        return []
    targets = _extract_click_targets_from_page(page)
    hover_targets: list[dict[str, str]] = []
    for item in targets:
        text = item.get("text", "")
        if not text or text in before_texts or text == target.get("text", ""):
            continue
        if item not in hover_targets:
            hover_targets.append(item)
    return hover_targets[:12]


def _extract_click_targets_from_page(page: Any) -> list[dict[str, str]]:
    raw_items = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a,button,[role="button"],[role="menuitem"],input[type="button"],input[type="submit"]'))
          .map((el) => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').trim();
            const inNavigation = !!el.closest('header,nav,[role="navigation"],.nav,.navbar,.menu,.header');
            return {
              text,
              visible: !!(rect.width || rect.height) && style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || 1) !== 0,
              in_navigation: inNavigation || rect.top < 140
            };
          }).filter((item) => item.visible && item.text)
        """
    )
    targets: list[dict[str, str]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        text = normalize_text(str(item.get("text", "")))
        if not text:
            continue
        target_type = "menu" if item.get("in_navigation") or _looks_like_navigation_click(text) else "action"
        if target_type == "action" and not _looks_like_action_click(text):
            continue
        target = {"type": target_type, "text": text[:120]}
        if target not in targets:
            targets.append(target)
    return targets


def _normalize_target_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {"type": "", "text": ""}
    target_type = str(value.get("type") or "").strip().lower()
    if target_type not in {"menu", "action"}:
        target_type = ""
    return {"type": target_type, "text": normalize_text(str(value.get("text") or ""))}


def _click_target_text(page: Any, target_text: str) -> None:
    last_error: Exception | None = None
    for locator in _target_locators(page, target_text):
        try:
            locator.click(timeout=3000)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    if last_error:
        raise last_error


def _target_locator(page: Any, target_text: str) -> Any:
    return _target_locators(page, target_text)[0]


def _target_locators(page: Any, target_text: str) -> list[Any]:
    text = normalize_text(target_text)
    return [
        page.get_by_text(text, exact=True).first,
        page.locator("header,nav,[role='navigation'],.nav,.navbar,.menu,.header").get_by_text(text, exact=True).first,
        page.locator("a,button,[role='button']").filter(has_text=text).first,
    ]


def _click_menu_text(page: Any, menu_text: str) -> None:
    _click_target_text(page, menu_text)


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
