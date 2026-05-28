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
        if "点击链路选择" in system_text or "hover_targets" in system_text:
            payload = _extract_json_object(last_user, "悬停证据")
            hover_targets = payload.get("hover_targets") if isinstance(payload.get("hover_targets"), list) else []
            return json.dumps(
                {"next_action": self._select_target([item for item in hover_targets if isinstance(item, dict)]), "reason": "选择最相关的悬停目标"},
                ensure_ascii=False,
                indent=2,
            )
        if (
            "recruitment_period" in system_text
            or "官方招聘活动时间安排" in system_text
            or "时间 agent" in system_text
            or "latest_posted_at" in system_text
        ):
            return json.dumps(self._recruitment_period_agent(last_user), ensure_ascii=False, indent=2)
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

    def _recruitment_period_agent(self, prompt_text: str) -> dict[str, Any]:
        job_role = _extract_after_label(prompt_text, "岗位") or "招聘岗位"
        payload = _extract_json_object(prompt_text, "页面证据")
        observation = payload.get("observation") if isinstance(payload.get("observation"), dict) else {}
        title = str(observation.get("title") or payload.get("title", ""))
        text = " ".join(
            [
                str(observation.get("content") or observation.get("visible_text_excerpt", "")),
                str(payload.get("text", "")),
                json.dumps(observation.get("sections", []), ensure_ascii=False),
            ]
        )
        menus = observation.get("menus") if isinstance(observation.get("menus"), list) else []
        actions = observation.get("actions") if isinstance(observation.get("actions"), list) else []
        click_targets = self._click_targets(menus, actions)
        compact = f"{title} {text}".lower()
        candidates = self._extract_date_candidates(compact)
        if candidates and any(keyword in compact for keyword in ("报名", "投递", "网申", "截止", "时间", "日程", "流程", "批次")):
            recruitment_period = " - ".join(candidates[:2]) if len(candidates) >= 2 else candidates[0]
            return {
                "job_role": job_role,
                "is_sufficient": True,
                "reason": "页面已包含官方招聘活动时间安排信号",
                "next_action": {"type": "", "text": ""},
                "period_company": str(payload.get("company", "")),
                "recruitment_period": recruitment_period,
                "application_start": candidates[0] if len(candidates) >= 2 else "",
                "application_deadline": candidates[-1],
                "period_evidence": "页面包含报名/投递/网申/截止/流程等时间安排语义",
                "confidence": "high",
            }
        return {
            "job_role": job_role,
            "is_sufficient": False,
            "reason": "页面没有明确招聘时间段或投递截止时间，需要继续看下一跳",
            "next_action": self._select_target(click_targets),
            "period_company": str(payload.get("company", "")),
            "recruitment_period": "",
            "application_start": "",
            "application_deadline": "",
            "period_evidence": "",
            "confidence": "low",
        }

    def _channel_status_agent(self, prompt_text: str) -> dict[str, Any]:
        job_role = _extract_after_label(prompt_text, "岗位") or "招聘岗位"
        payload = _extract_json_object(prompt_text, "页面证据")
        observation = payload.get("observation") if isinstance(payload.get("observation"), dict) else {}
        title = str(observation.get("title") or payload.get("title", ""))
        text = " ".join(
            [
                str(observation.get("content") or observation.get("visible_text_excerpt", "")),
                str(payload.get("text", "")),
                json.dumps(observation.get("sections", []), ensure_ascii=False),
            ]
        )
        menus = observation.get("menus") if isinstance(observation.get("menus"), list) else []
        actions = observation.get("actions") if isinstance(observation.get("actions"), list) else []
        click_targets = self._click_targets(menus, actions)
        compact = f"{title} {text}".lower()
        if any(keyword in compact for keyword in ("已结束", "停止招聘", "暂停招聘", "已关闭", "招聘结束", "未开启")):
            return {
                "job_role": job_role,
                "is_sufficient": True,
                "reason": "页面已包含明确关闭信号",
                "next_action": {"type": "", "text": ""},
                "channel_status": "closed",
                "confidence": "high",
            }
        if any(keyword in compact for keyword in ("校招进行中", "校招开启", "校园招聘", "招聘中", "正在招聘", "开放投递", "开启投递")):
            return {
                "job_role": job_role,
                "is_sufficient": True,
                "reason": "页面已包含明确开启信号",
                "next_action": {"type": "", "text": ""},
                "channel_status": "open",
                "confidence": "high",
            }
        return {
            "job_role": job_role,
            "is_sufficient": False,
            "reason": "页面没有明确开放或关闭信号，需要继续看下一跳",
            "next_action": self._select_target(click_targets),
            "channel_status": "unknown",
            "confidence": "low",
        }

    @staticmethod
    def _click_targets(menus: list[Any], actions: list[Any]) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []
        for target_type, items in (("menu", menus), ("action", actions)):
            for item in items:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text", "")).strip()
                if text:
                    targets.append({"type": target_type, "text": text})
        return targets

    @staticmethod
    def _select_target(targets: list[dict[str, str]]) -> dict[str, str]:
        preferred = ("校园招聘", "校招", "实习就业", "实习", "招聘动态", "招聘公告", "报名", "投递", "职位", "查看岗位")
        for keyword in preferred:
            for target in targets:
                if keyword in target["text"]:
                    return target
        return targets[0] if targets else {"type": "", "text": ""}

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
