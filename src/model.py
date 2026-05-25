"""Model backend helpers for the second-version job-watch workflow."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from .config import ModelBackendSettings
from .crawler import search_company_candidates
from .models import AnalysisResult, CompanyCandidate, CrawledPage


logger = logging.getLogger(__name__)


class ModelBackend(Protocol):
    def chat(self, messages: Sequence[dict[str, str]]) -> str:
        """Return the model response for the provided chat messages."""


@dataclass(slots=True)
class OpenAICompatibleBackend:
    settings: ModelBackendSettings

    def chat(self, messages: Sequence[dict[str, str]]) -> str:
        if not self.settings.api_base_url.strip():
            raise ValueError("OpenAI-compatible backend requires api_base_url")
        if not self.settings.api_key.strip():
            raise ValueError("OpenAI-compatible backend requires api_key")

        endpoint = _normalize_openai_endpoint(self.settings.api_base_url)
        payload = {
            "model": self.settings.model,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "messages": list(messages),
        }
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            timeout=self.settings.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("unexpected model response structure") from exc


@dataclass(slots=True)
class HeuristicBackend:
    timeout_seconds: int

    def chat(self, messages: Sequence[dict[str, str]]) -> str:
        last_user = _last_user_message(messages)
        if "抓取到的招聘页面" in last_user or "最近一次招聘信息" in last_user:
            return json.dumps(self._analyze(last_user), ensure_ascii=False, indent=2)
        return json.dumps(self._select(last_user), ensure_ascii=False, indent=2)

    def _select(self, prompt_text: str) -> dict[str, Any]:
        job_role = _extract_after_label(prompt_text, "岗位") or "招聘岗位"
        top_x_text = _extract_after_label(prompt_text, "数量") or "3"
        company_filters = _extract_after_label(prompt_text, "筛选条件")
        match = re.search(r"\d+", top_x_text)
        top_x = max(1, int(match.group(0))) if match else 3
        candidates = search_company_candidates(
            job_role,
            top_x,
            timeout_seconds=self.timeout_seconds,
            company_filters=company_filters,
        )
        return {
            "job_role": job_role,
            "top_x": top_x,
            "companies": [candidate.to_dict() for candidate in candidates],
        }

    def _analyze(self, prompt_text: str) -> dict[str, Any]:
        job_role = _extract_after_label(prompt_text, "岗位") or "招聘岗位"
        company_payload = _extract_json_list(prompt_text, "第一阶段公司结果")
        page_payload = _extract_json_list(prompt_text, "抓取到的招聘页面")
        candidates = [CompanyCandidate(**item) for item in company_payload if isinstance(item, dict)]
        pages = [CrawledPage(**item) for item in page_payload if isinstance(item, dict)]
        result = analyze_latest_posting(job_role, candidates, pages)
        return result.to_dict()


def create_backend(settings: ModelBackendSettings) -> ModelBackend:
    backend_name = settings.backend.strip().lower()
    if backend_name in {"openai", "openai_compatible", "openai-compatible", "api", "proxy", "relay"}:
        return OpenAICompatibleBackend(settings)
    return HeuristicBackend(timeout_seconds=settings.timeout_seconds)


def _normalize_openai_endpoint(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    if "/v1/" in normalized:
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def analyze_latest_posting(
    job_role: str,
    selected_companies: Sequence[CompanyCandidate],
    crawled_pages: Sequence[CrawledPage],
) -> AnalysisResult:
    latest_company = ""
    latest_posted_at = ""
    latest_channel_status = "unknown"
    best_score = -1

    for page in crawled_pages:
        score, posted_at = _score_page(page)
        if score > best_score:
            best_score = score
            latest_company = page.company
            latest_posted_at = posted_at
            latest_channel_status = page.channel_status or "unknown"

    if not latest_company and selected_companies:
        latest_company = selected_companies[0].name

    confidence = "high" if latest_posted_at else "low"

    return AnalysisResult(
        job_role=job_role,
        latest_company=latest_company,
        latest_posted_at=latest_posted_at,
        channel_status=latest_channel_status,
        confidence=confidence,
    )


def _score_page(page: CrawledPage) -> tuple[int, str]:
    best = ""
    best_score = -1
    for candidate in page.date_candidates:
        score = _date_score(candidate)
        if score > best_score:
            best_score = score
            best = candidate
    return best_score, best


def _date_score(value: str) -> int:
    compact = value.strip()
    if not compact:
        return -1
    if re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", compact):
        return 5
    if re.search(r"\d{4}年\d{1,2}月\d{1,2}日?", compact):
        return 5
    if re.search(r"\d{4}[-/.]\d{1,2}", compact):
        return 4
    if re.search(r"\d{1,2}月\d{1,2}日", compact):
        return 3
    return 1


def _last_user_message(messages: Sequence[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") in {"user", "human"}:
            return str(message.get("content", ""))
    return str(messages[-1].get("content", "")) if messages else ""


def _extract_after_label(text: str, label: str) -> str:
    pattern = rf"{re.escape(label)}[:：]\s*(.+)"
    match = re.search(pattern, text)
    return match.group(1).splitlines()[0].strip() if match else ""


def _extract_json_list(text: str, label: str) -> list[dict[str, Any]]:
    marker = f"{label}："
    start = text.find(marker)
    if start == -1:
        return []
    remainder = text[start + len(marker):].lstrip()
    first_bracket = remainder.find("[")
    if first_bracket == -1:
        return []
    json_text = remainder[first_bracket:]
    decoder = json.JSONDecoder()
    try:
        parsed, _ = decoder.raw_decode(json_text)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
