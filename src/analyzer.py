from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
import re

import requests

from src.models import JobPosting, MatchResult


@dataclass(slots=True)
class AnalyzerSettings:
    keywords: list[str]
    companies: list[str]
    min_score: float = 1.0


@dataclass(slots=True)
class ModelBackendSettings:
    backend: str = "rule"
    api_base_url: str = ""
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout_seconds: int = 30
    temperature: float = 0.2
    max_tokens: int = 512
    system_prompt: str = (
        "你是招聘信息分析助手。请根据给定岗位信息判断是否匹配目标条件，"
        "并只返回 JSON，格式为 {\"matched\": true/false, \"score\": number, \"reasons\": [\"...\"]}。"
    )


class RuleBasedAnalyzer:
    def __init__(self, settings: AnalyzerSettings) -> None:
        self.settings = settings

    def analyze_job(self, job: JobPosting) -> MatchResult:
        score = 0.0
        reasons: list[str] = []
        text = " ".join([job.title, job.company, job.location, job.description]).lower()

        if self.settings.companies and job.company.lower() in {company.lower() for company in self.settings.companies}:
            score += 1.0
            reasons.append(f"company matched: {job.company}")

        for keyword in self.settings.keywords:
            if keyword.lower() in text:
                score += 1.0
                reasons.append(f"keyword matched: {keyword}")

        matched = score >= self.settings.min_score
        if not reasons:
            reasons.append("no keyword or company match")
        return MatchResult(job=job, matched=matched, score=score, reasons=reasons)

    def analyze(self, jobs: Iterable[JobPosting]) -> list[MatchResult]:
        return [self.analyze_job(job) for job in jobs]


class OpenAICompatibleAnalyzer:
    def __init__(self, settings: AnalyzerSettings, backend: ModelBackendSettings) -> None:
        if not backend.api_base_url.strip():
            raise ValueError("OpenAI-compatible backend requires api_base_url")
        if not backend.api_key.strip():
            raise ValueError("OpenAI-compatible backend requires api_key")

        self.settings = settings
        self.backend = backend

    def _build_user_prompt(self, job: JobPosting) -> str:
        keyword_text = ", ".join(self.settings.keywords) or "无"
        company_text = ", ".join(self.settings.companies) or "无"
        return (
            "岗位信息如下：\n"
            f"标题：{job.title}\n"
            f"公司：{job.company}\n"
            f"地点：{job.location}\n"
            f"发布时间：{job.posted_at}\n"
            f"描述：{job.description}\n\n"
            f"目标关键词：{keyword_text}\n"
            f"目标公司：{company_text}\n"
            "请判断该岗位是否匹配。"
        )

    @staticmethod
    def _extract_json_block(content: str) -> str:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()

        if text.startswith("{") and text.endswith("}"):
            return text

        match = re.search(r"\{.*\}", text, flags=re.S)
        if match:
            return match.group(0)
        raise ValueError("model response does not contain JSON")

    def _parse_response(self, content: str, job: JobPosting) -> MatchResult:
        json_text = self._extract_json_block(content)
        payload = json.loads(json_text)
        matched = bool(payload.get("matched", False))
        score = float(payload.get("score", 0.0))
        reasons_value = payload.get("reasons", [])
        if isinstance(reasons_value, list):
            reasons = [str(item) for item in reasons_value]
        else:
            reasons = [str(reasons_value)] if reasons_value else []
        if not reasons:
            reasons = ["model returned no reasons"]
        return MatchResult(job=job, matched=matched, score=score, reasons=reasons)

    def analyze_job(self, job: JobPosting) -> MatchResult:
        payload = {
            "model": self.backend.model,
            "temperature": self.backend.temperature,
            "max_tokens": self.backend.max_tokens,
            "messages": [
                {"role": "system", "content": self.backend.system_prompt},
                {"role": "user", "content": self._build_user_prompt(job)},
            ],
        }
        response = requests.post(
            f"{self.backend.api_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.backend.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.backend.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("unexpected model response structure") from exc
        return self._parse_response(str(content), job)

    def analyze(self, jobs: Iterable[JobPosting]) -> list[MatchResult]:
        return [self.analyze_job(job) for job in jobs]


class LLMAnalyzer:
    """Switchable analyzer that can use a local rule backend or an OpenAI-compatible API."""

    def __init__(self, settings: AnalyzerSettings, backend: ModelBackendSettings | None = None) -> None:
        backend = backend or ModelBackendSettings()
        backend_name = backend.backend.strip().lower()
        if backend_name in {"openai", "openai_compatible", "openai-compatible", "api"}:
            self._delegate = OpenAICompatibleAnalyzer(settings, backend)
        else:
            self._delegate = RuleBasedAnalyzer(settings)

    def analyze(self, jobs: Iterable[JobPosting]) -> list[MatchResult]:
        return self._delegate.analyze(jobs)
