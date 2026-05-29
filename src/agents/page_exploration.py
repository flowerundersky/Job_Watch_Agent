"""Shared page-exploration agent loop."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from ..config import RuntimeSettings
from ..crawler import crawl_company_page, crawl_url, resolve_click_target_to_url
from ..models import CompanyCandidate, CrawledPage
from ..json_utils import extract_json_object


class PageExplorationAgent(ABC):
    """Base class for agents that explore recruitment pages through clicks."""

    task_type: str = ""
    log_label: str = ""

    def __init__(self, backend: Any, *, job_role: str, runtime: RuntimeSettings, max_hops: int = 3) -> None:
        self.backend = backend
        self.job_role = job_role
        self.runtime = runtime
        self.max_hops = max_hops

    def run(self, candidate: CompanyCandidate) -> CrawledPage:
        visited_urls: list[str] = []
        current_url = candidate.recruitment_url
        final_page: CrawledPage | None = None
        trace_steps: list[dict[str, Any]] = []

        for hop_index in range(1, self.max_hops + 1):
            page = crawl_url(
                candidate.name,
                current_url,
                timeout_seconds=self.runtime.timeout_seconds,
                browser_name=self.runtime.browser_name,
                render_retries=self.runtime.render_retries,
                max_crawl_chars=self.runtime.max_crawl_chars,
                max_links_per_page=self.runtime.max_links_per_page,
            )
            print(f"公司 {candidate.name} {self.log_label} agent 已爬取页面: {page.page_url}")
            visited_urls.append(page.page_url)

            raw_model_output = self.backend.chat(self.build_messages(candidate, page))
            decision = extract_json_object(raw_model_output)
            self.apply_decision(page, decision)

            next_action = {} if page.is_sufficient else self._normalize_next_action(page.observation, decision)
            page.selected_menu = str(next_action.get("text", ""))
            page.selected_action_type = str(next_action.get("type", ""))
            resolved_action = {} if page.is_sufficient else self._resolve_next_action(page.page_url, next_action, candidate)
            page.next_hops = [str(resolved_action.get("url", ""))] if resolved_action.get("url") else []
            page.action_chain = list(resolved_action.get("chain", [])) if isinstance(resolved_action.get("chain"), list) else []
            page.visited_urls = list(visited_urls)
            page.task_type = self.task_type

            trace_steps.append(
                self._build_trace_step(
                    candidate=candidate,
                    page=page,
                    hop_index=hop_index,
                    requested_url=current_url,
                    raw_model_output=raw_model_output,
                    decision=decision,
                )
            )
            page.trace_steps = list(trace_steps)
            final_page = page
            if page.is_sufficient or not page.next_hops:
                break
            current_url = page.next_hops[0]

        print(self.completion_message(candidate, final_page))
        return final_page or crawl_company_page(
            candidate,
            timeout_seconds=self.runtime.timeout_seconds,
            browser_name=self.runtime.browser_name,
            render_retries=self.runtime.render_retries,
            max_crawl_chars=self.runtime.max_crawl_chars,
            max_links_per_page=self.runtime.max_links_per_page,
        )

    @abstractmethod
    def build_messages(self, candidate: CompanyCandidate, page: CrawledPage) -> list[dict[str, str]]:
        """Build the task-specific model prompt."""

    @abstractmethod
    def apply_decision(self, page: CrawledPage, decision: dict[str, Any]) -> None:
        """Apply the task-specific model decision to the crawled page."""

    @abstractmethod
    def completion_message(self, candidate: CompanyCandidate, page: CrawledPage | None) -> str:
        """Return a log line for the completed agent run."""

    def _normalize_next_action(self, observation: dict[str, Any], decision: dict[str, Any]) -> dict[str, str]:
        next_action = decision.get("next_action")
        if isinstance(next_action, dict):
            raw_type = str(next_action.get("type") or "").strip().lower()
            raw_text = str(next_action.get("text") or "").strip()
        else:
            raw_type = "menu"
            raw_text = str(decision.get("next_menu") or "").strip()

        candidates = self._observation_click_targets(observation)
        for candidate in candidates:
            if candidate["type"] == raw_type and candidate["text"] == raw_text:
                return candidate
        for candidate in candidates:
            if raw_text and candidate["type"] == raw_type and (raw_text in candidate["text"] or candidate["text"] in raw_text):
                return candidate
        for candidate in candidates:
            if raw_text and (raw_text in candidate["text"] or candidate["text"] in raw_text):
                return candidate
        return {}

    @staticmethod
    def _observation_click_targets(observation: dict[str, Any]) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []
        for target_type, key in (("menu", "menus"), ("action", "actions")):
            items = observation.get(key) if isinstance(observation.get(key), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                if text:
                    target = {"type": target_type, "text": text}
                    if target not in targets:
                        targets.append(target)
        return targets

    def _resolve_next_action(self, page_url: str, target: dict[str, str], candidate: CompanyCandidate) -> dict[str, Any]:
        if not target.get("text"):
            return {}
        return resolve_click_target_to_url(
            page_url,
            target,
            lambda parent, hover_targets: self._choose_hover_target(candidate, parent, hover_targets),
            timeout_seconds=self.runtime.timeout_seconds,
            browser_name=self.runtime.browser_name,
            render_retries=self.runtime.render_retries,
        )

    def _choose_hover_target(self, candidate: CompanyCandidate, parent: dict[str, str], hover_targets: list[dict[str, str]]) -> dict[str, str]:
        if not hover_targets:
            return {}
        raw_output = self.backend.chat(self.build_hover_messages(candidate, parent, hover_targets))
        try:
            decision = extract_json_object(raw_output)
        except Exception:  # noqa: BLE001
            return hover_targets[0]
        next_action = decision.get("next_action")
        if not isinstance(next_action, dict):
            return hover_targets[0]
        normalized = {"type": str(next_action.get("type") or "").strip(), "text": str(next_action.get("text") or "").strip()}
        for target in hover_targets:
            if target == normalized:
                return target
        for target in hover_targets:
            if normalized["text"] and (normalized["text"] in target["text"] or target["text"] in normalized["text"]):
                return target
        return hover_targets[0]

    def build_hover_messages(self, candidate: CompanyCandidate, parent_target: dict[str, str], hover_targets: list[dict[str, str]]) -> list[dict[str, str]]:
        task_label = "招聘时间段" if self.task_type == "period" else "校园招聘通道状态"
        evidence = {
            "company": candidate.name,
            "task": task_label,
            "parent_target": parent_target,
            "hover_targets": hover_targets,
        }
        return [
            {
                "role": "system",
                "content": (
                    "你是一个为网页点击链路选择下一步目标的助手。"
                    "用户已经悬停 parent_target，页面出现 hover_targets。"
                    f"你的目标是继续寻找最可能帮助判断{task_label}的入口。"
                    "只能从 hover_targets 中选择一个。不要输出 URL。"
                    "优先选择校园招聘、实习生招聘、招聘公告、招聘动态、招聘项目、校招项目、应届生、毕业生、网申、投递、报名、流程安排、招聘日程、职位、查看岗位等目标。"
                    "只输出 JSON：{\"next_action\":{\"type\":\"menu|action\",\"text\":\"...\"},\"reason\":\"...\"}"
                ),
            },
            {"role": "user", "content": f"悬停证据：{json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))}"},
        ]

    def _build_trace_step(
        self,
        *,
        candidate: CompanyCandidate,
        page: CrawledPage,
        hop_index: int,
        requested_url: str,
        raw_model_output: str,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "company": candidate.name,
            "rank": candidate.rank,
            "task_type": self.task_type,
            "hop_index": hop_index,
            "requested_url": requested_url,
            "page_url": page.page_url,
            "site_type": page.site_type,
            "title": page.title,
            "observation": page.observation,
            "text_excerpt": page.text[:1200],
            "recruitment_period": page.recruitment_period,
            "application_start": page.application_start,
            "application_deadline": page.application_deadline,
            "period_evidence": page.period_evidence,
            "date_candidates": page.date_candidates[:5],
            "error": page.error,
            "raw_model_output": raw_model_output.strip(),
            "decision": decision,
            "selected_menu": page.selected_menu,
            "selected_action_type": page.selected_action_type,
            "action_chain": page.action_chain,
            "next_hops": page.next_hops,
            "selected_next_hop": page.next_hops[0] if page.next_hops else "",
            "is_sufficient": page.is_sufficient,
            "decision_reason": page.decision_reason,
            "confidence": page.decision_confidence,
        }
