"""Channel status page agent."""

from __future__ import annotations

import json
from typing import Any

from ..models import CompanyCandidate, CrawledPage
from .page_exploration import PageExplorationAgent


class ChannelStatusAgent(PageExplorationAgent):
    task_type = "channel"
    log_label = "通道"

    def build_messages(self, candidate: CompanyCandidate, page: CrawledPage) -> list[dict[str, str]]:
        evidence = {"company": candidate.name, "page_url": page.page_url, "observation": page.observation}
        return [
            {
                "role": "system",
                "content": (
                    "你是一个在当前网页页面寻找校园招聘通道的agent。"
                    "页面证据只包含渲染后的页面内容 content、导航菜单 menus、正文可点击目标 actions。"
                    "你只做两件事：判断当前页是否足以判断校园招聘通道状态；如果不够，只能从 menus 或 actions 里选择一个目标作为下一跳。"
                    "open 表示页面能看出正在招聘、开放投递、存在有效岗位列表或投递入口。"
                    "closed 表示页面能看出已结束、暂停招聘、暂无职位、未开放或停止投递。"
                    "unknown 表示证据不足。不要因为只出现公司名、岗位名、日期或招聘字样就判断 open。"
                    "不要输出 URL；next_action.type 必须是 menu 或 action；next_action.text 必须是 menus 或 actions 中出现过的 text。"
                    "只输出一个 JSON 对象，字段必须齐全；未知内容用 unknown、空数组或 low。"
                    "{\"is_sufficient\":true|false,\"reason\":\"...\",\"next_action\":{\"type\":\"menu|action\",\"text\":\"...\"},\"channel_status\":\"open|closed|unknown\",\"confidence\":\"high|medium|low\"}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"页面证据：{json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))}\n"
                    "如果当前证据足够，就返回 true 并输出 channel_status；如果不够，就返回 false 并从 menus 或 actions 里选择 next_action。"
                ),
            },
        ]

    def apply_decision(self, page: CrawledPage, decision: dict[str, Any]) -> None:
        page.is_sufficient = bool(decision.get("is_sufficient"))
        page.decision_reason = str(decision.get("reason", "")).strip()
        page.channel_status = str(decision.get("channel_status", page.channel_status or "unknown")).strip() or "unknown"
        page.decision_confidence = str(decision.get("confidence", "low")).strip() or "low"

    def completion_message(self, candidate: CompanyCandidate, page: CrawledPage | None) -> str:
        status = page.channel_status if page else "unknown"
        return f"公司 {candidate.name} 通道 agent 已完成，通道状态: {status}"
