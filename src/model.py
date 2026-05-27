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
from .models import CompanyCandidate


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
        system_text = " \n".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "system"
        )
        last_user = _last_user_message(messages)
        if "latest_posted_at" in system_text or "招聘信息最新发布日期" in system_text or "时间 agent" in system_text:
            return json.dumps(self._latest_date_agent(last_user), ensure_ascii=False, indent=2)
        if "channel_status" in system_text or "校园招聘通道" in system_text or "通道 agent" in system_text:
            return json.dumps(self._channel_status_agent(last_user), ensure_ascii=False, indent=2)
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

    def _latest_date_agent(self, prompt_text: str) -> dict[str, Any]:
        job_role = _extract_after_label(prompt_text, "岗位") or "招聘岗位"
        payload = _extract_json_object(prompt_text, "页面证据")
        title = str(payload.get("title", ""))
        text = str(payload.get("text", ""))
        links = [str(item).strip() for item in payload.get("links", []) if str(item).strip()]
        compact = f"{title} {text}".lower()
        candidates = self._extract_date_candidates(compact)
        if candidates:
            latest_posted_at = candidates[0]
            return {
                "job_role": job_role,
                "is_sufficient": True,
                "reason": "页面已包含明确日期信号",
                "next_hops": [],
                "latest_company": str(payload.get("company", "")),
                "latest_posted_at": latest_posted_at,
                "confidence": "high",
            }
        return {
            "job_role": job_role,
            "is_sufficient": False,
            "reason": "页面没有明确日期，需要继续看下一跳",
            "next_hops": links[:2],
            "latest_company": str(payload.get("company", "")),
            "latest_posted_at": "",
            "confidence": "low",
        }

    def _channel_status_agent(self, prompt_text: str) -> dict[str, Any]:
        job_role = _extract_after_label(prompt_text, "岗位") or "招聘岗位"
        payload = _extract_json_object(prompt_text, "页面证据")
        title = str(payload.get("title", ""))
        text = str(payload.get("text", ""))
        links = [str(item).strip() for item in payload.get("links", []) if str(item).strip()]
        compact = f"{title} {text}".lower()
        if any(keyword in compact for keyword in ("已结束", "停止招聘", "暂停招聘", "已关闭", "招聘结束", "未开启")):
            return {
                "job_role": job_role,
                "is_sufficient": True,
                "reason": "页面已包含明确关闭信号",
                "next_hops": [],
                "channel_status": "closed",
                "confidence": "high",
            }
        if any(keyword in compact for keyword in ("校招进行中", "校招开启", "校园招聘", "招聘中", "正在招聘", "开放投递", "开启投递")):
            return {
                "job_role": job_role,
                "is_sufficient": True,
                "reason": "页面已包含明确开启信号",
                "next_hops": [],
                "channel_status": "open",
                "confidence": "high",
            }
        return {
            "job_role": job_role,
            "is_sufficient": False,
            "reason": "页面没有明确开放或关闭信号，需要继续看下一跳",
            "next_hops": links[:2],
            "channel_status": "unknown",
            "confidence": "low",
        }

    def _extract_date_candidates(self, text: str) -> list[str]:
        candidates: list[str] = []
        for pattern in (
            r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}",
            r"\d{4}年\d{1,2}月\d{1,2}日?",
            r"\d{4}[-/.]\d{1,2}",
            r"\d{1,2}月\d{1,2}日",
        ):
            for match in re.findall(pattern, text):
                if match not in candidates:
                    candidates.append(match)
        return candidates


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


def _last_user_message(messages: Sequence[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") in {"user", "human"}:
            return str(message.get("content", ""))
    return str(messages[-1].get("content", "")) if messages else ""


def _extract_after_label(text: str, label: str) -> str:
    pattern = rf"{re.escape(label)}[:：]\s*(.+)"
    match = re.search(pattern, text)
    return match.group(1).splitlines()[0].strip() if match else ""


def _extract_json_object(text: str, label: str) -> dict[str, Any]:
    marker = f"{label}："
    start = text.find(marker)
    if start == -1:
        return {}
    remainder = text[start + len(marker):].lstrip()
    first_brace = remainder.find("{")
    if first_brace == -1:
        return {}
    json_text = remainder[first_brace:]
    decoder = json.JSONDecoder()
    try:
        parsed, _ = decoder.raw_decode(json_text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
