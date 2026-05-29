"""Recruitment period page agent."""

from __future__ import annotations

import json
from typing import Any

from ..models import CompanyCandidate, CrawledPage
from .page_exploration import PageExplorationAgent


class RecruitmentPeriodAgent(PageExplorationAgent):
    task_type = "period"
    log_label = "时间"

    def build_messages(self, candidate: CompanyCandidate, page: CrawledPage) -> list[dict[str, str]]:
        evidence = {"company": candidate.name, "page_url": page.page_url, "observation": page.observation}
        return [
            {
                "role": "system",
                "content": (
                    "你是一个在当前网页页面抓取官方招聘活动时间安排的agent。"
                    "页面证据只包含渲染后的页面内容 content、导航菜单 menus、正文可点击目标 actions。"
                    "你只做两件事：判断当前页内容是否足够提取官方招聘活动的报名、投递、网申、截止、流程或批次的时间；如果不够，只能从 menus 或 actions 里选择一个目标作为下一跳。"
                    "目标不是单个岗位的发布时间、更新时间或发布日期。不要把岗位详情页里的 posted_at、更新时间、发布日期当作 recruitment_period。"
                    "recruitment_period 应来自官方招聘公告、校招项目、实习项目、招聘动态、招聘流程、日程安排、网申/投递时间或批次说明。"
                    "如果当前页只是岗位列表或岗位详情，但没有招聘时间段/截止时间，不要返回 is_sufficient=true。"
                    "下一跳优先选择含有校园招聘、实习生招聘、招聘公告、招聘动态、招聘项目、校招项目、应届生、毕业生、网申、投递、报名、流程安排、招聘日程等语义的目标。"
                    "不要输出 URL；next_action.type 必须是 menu 或 action；next_action.text 必须是 menus 或 actions 中出现过的 text。"
                    "只输出一个 JSON 对象，字段必须齐全；未知内容用空字符串、空数组或 low。"
                    "{\"is_sufficient\":true|false,\"reason\":\"...\",\"next_action\":{\"type\":\"menu|action\",\"text\":\"...\"},\"period_company\":\"...\",\"recruitment_period\":\"...\",\"application_start\":\"...\",\"application_deadline\":\"...\",\"period_evidence\":\"...\",\"confidence\":\"high|medium|low\"}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"页面证据：{json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))}\n"
                    "如果当前证据足够，就返回 true 并输出 recruitment_period/application_start/application_deadline；如果不够，就返回 false 并从 menus 或 actions 里选择 next_action。"
                ),
            },
        ]

    def apply_decision(self, page: CrawledPage, decision: dict[str, Any]) -> None:
        page.is_sufficient = bool(decision.get("is_sufficient"))
        page.decision_reason = str(decision.get("reason", "")).strip()
        page.recruitment_period = str(decision.get("recruitment_period", "")).strip()
        page.application_start = str(decision.get("application_start", "")).strip()
        page.application_deadline = str(decision.get("application_deadline", "")).strip()
        page.period_evidence = str(decision.get("period_evidence", "")).strip()
        page.latest_posted_at = str(
            decision.get("latest_posted_at") or page.recruitment_period or page.application_deadline or page.application_start or ""
        ).strip()
        page.decision_confidence = str(decision.get("confidence", "low")).strip() or "low"
        page.date_candidates = [page.latest_posted_at] if page.latest_posted_at else list(page.date_candidates)

    def completion_message(self, candidate: CompanyCandidate, page: CrawledPage | None) -> str:
        period = page.recruitment_period if page else ""
        return f"公司 {candidate.name} 时间 agent 已完成，招聘时间段: {period or '未找到'}"
