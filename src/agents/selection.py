"""
author: goldstar
date: 2024-06-05
agent: 公司筛选 agent，负责根据岗位名称和筛选条件选出目标公司和招聘官网入口。
并通过爬虫助手抓取招聘官网,使用“渲染”模拟人类找工作通道行为，然后进行简历的投递。
并建立记忆系统，已经找到并投递的公司不再投递。

agent的运行时应该是输入输出都有

输出结果包括：
- selected_companies: 选出的目标公司列表。
- recruitment_urls: 校招官网入口列表
"""

from __future__ import annotations

# 加载区
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlparse

from ..model.modelresults import CompanyCandidate
from ..tools.json_utils import extract_json_object

# 数据结构区
@dataclass(slots=True)
class CompanySelectionInput:
    job_role: str
    top_x: int
    company_filters: str = ""

@dataclass(slots=True)
class CompanySelectionLLMCompany:
    name: str
    recruitment_url: str
    rank: int = 0

@dataclass(slots=True)
class CompanySelectionResult:
    job_role: str
    top_x: int
    selected: list[CompanyCandidate]
    missing: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_role": self.job_role,
            "top_x": self.top_x,
            "selected": [item.to_dict() for item in self.selected],
            "missing": self.missing,
        }

# 业务区
def build_default_company_selection_input() -> CompanySelectionInput:
    return CompanySelectionInput(
        job_role="AI应用工程师或者agent开发工程师或者harness开发工程师",
        top_x=3,
        company_filters="优先中文招聘网站",
    )


# agent 主体区
class CompanySelectionAgent:
    """
    初始化
    """
    def __init__(self, backend: Any, selection_input: CompanySelectionInput) -> None:
        self.backend = backend
        self.input = selection_input

    """运行"""

    def run(self) -> CompanySelectionResult:
        self.input = build_default_company_selection_input()
        messages = self._build_messages()
        raw_output = self.backend.chat(messages)
        payload = extract_json_object(raw_output)
        candidates, missing_candidates = self._parse_candidates(payload)

        attempts = 0
        while len(candidates) < self.input.top_x and attempts < 2:
            attempts += 1
            current_payload = [candidate.to_dict() for candidate in candidates]
            messages = messages + [
                {"role": "assistant", "content": raw_output},
                *self._build_retry_message(current_payload),
            ]
            raw_output = self.backend.chat(messages)
            payload = extract_json_object(raw_output)
            new_candidates, rejected_items = self._parse_candidates(payload)
            candidates = self._merge_candidates(candidates, new_candidates)
            missing_candidates = self._merge_missing(missing_candidates, rejected_items)

        selected = candidates[: self.input.top_x]
        missing = self._finalize_missing(selected, missing_candidates)
        return CompanySelectionResult(
            job_role=self.input.job_role,
            top_x=self.input.top_x,
            selected=selected,
            missing=missing,
        )


    """构造公司筛选 agent 的初始提示词。"""
    def _build_messages(self) -> list[dict[str, str]]:
        filter_text = f"\n筛选条件：{self.input.company_filters}" if self.input.company_filters.strip() else ""
        return [
            {
                "role": "system",
                "content": (
                    "你是一个根据岗位名称和筛选条件搜索公司网站的助手。"
                    "我是一名快要毕业的大学生，想要了解哪些公司可能正在招聘某个岗位的员工和实习生，以及这些公司的招聘官网入口。"
                    f"你的任务是根据岗位名称和筛选条件选出会发布此岗位的最多{self.input.top_x} 家公司和该公司的招聘官网入口。"
                    f"recruitment_url里输出的是公司的招聘网站入口。只输出 JSON。最多返回{self.input.top_x}家；只返回你能给出招聘官网入口的公司；不足不要编造。"
                    f"输出的格式：{{\"job_role\":\"...\",\"top_x\":{self.input.top_x},\"companies\":[{{\"name\":\"...\",\"recruitment_url\":\"https://...\"}}]}}"
                    "只要总招聘页，不要返回校招专门页，第三方招聘平台、新闻稿、公众号文章、公司首页、岗位列表页。"
                    "最后达到的目标是帮助我快速锁定目标公司的招聘官网。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"岗位：{self.input.job_role}\n数量：{self.input.top_x}{filter_text}\n公司最好具备的条件：{self.input.company_filters}\n"
                    f"请返回最可能发布“{self.input.job_role}”招聘信息的前 {self.input.top_x} 家公司及其官方招聘官网入口。"
                ),
            },
        ]

    """构造补齐公司列表的追问提示词。"""
    def _build_retry_message(self, current_companies: list[dict[str, Any]]) -> list[dict[str, str]]:  
        filter_line = f"筛选条件：{self.input.company_filters}\n" if self.input.company_filters.strip() else ""
        missing_count = max(0, self.input.top_x - len(current_companies))
        return [
            {
                "role": "user",
                "content": (
                    f"岗位：{self.input.job_role}\n目标数量：{self.input.top_x}\n还缺少：{missing_count} 家\n"
                    f"{filter_line}"
                    f"当前已返回公司数：{len(current_companies)}\n"
                    f"当前结果：{json.dumps(current_companies, ensure_ascii=False, separators=(',', ':'))}\n"
                    f"请补齐到恰好 {self.input.top_x} 家公司，不要重复已有公司，只输出新增部分。"
                ),
            }
        ]

    """把模型 JSON 转成 CompanyCandidate，并把缺字段/不像招聘页的项放入 missing。"""
    def _parse_candidates(self, payload: dict[str, Any]) -> tuple[list[CompanyCandidate], list[dict[str, Any]]]:
        raw_companies = payload.get("companies", [])
        if not isinstance(raw_companies, list):
            raise ValueError("company selection output missing companies list")
        candidates: list[CompanyCandidate] = []
        missing: list[dict[str, Any]] = []
        for index, item in enumerate(raw_companies, start=1):
            if not isinstance(item, dict):
                missing.append({"rank": index, "missing_reason": "invalid item"})
                continue
            name = str(item.get("name") or item.get("company") or "").strip()
            recruitment_url = str(
                item.get("recruitment_url") or item.get("url") or item.get("career_url") or item.get("careers_url") or ""
            ).strip()
            if not name or not recruitment_url:
                missing.append({
                    "rank": int(item.get("rank") or index),
                    "name": name,
                    "recruitment_url": recruitment_url,
                    "missing_reason": "missing name or recruitment_url",
                })
                continue
            if not self._looks_like_recruitment_url(recruitment_url):
                missing.append({
                    "rank": int(item.get("rank") or index),
                    "name": name,
                    "recruitment_url": recruitment_url,
                    "missing_reason": "url not recruitment-like",
                })
                continue
            candidates.append(CompanyCandidate(
                rank=int(item.get("rank") or index),
                name=name,
                recruitment_url=recruitment_url,
                reason=str(item.get("reason") or "").strip(),
                raw=item,
            ))
        return candidates, missing

    @staticmethod
    def _merge_candidates(existing: list[CompanyCandidate], new_items: list[CompanyCandidate]) -> list[CompanyCandidate]:
        merged = list(existing)
        seen = {(item.name.strip().lower(), item.recruitment_url.strip().lower()) for item in merged}
        for item in new_items:
            key = (item.name.strip().lower(), item.recruitment_url.strip().lower())
            if key not in seen:
                merged.append(item)
                seen.add(key)
        for index, item in enumerate(merged, start=1):
            item.rank = index
        return merged

    @staticmethod
    def _merge_missing(existing: list[dict[str, Any]], new_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged = list(existing)
        seen = {(str(item.get("name", "")).lower(), str(item.get("recruitment_url", "")).lower()) for item in merged}
        for item in new_items:
            key = (str(item.get("name", "")).lower(), str(item.get("recruitment_url", "")).lower())
            if key not in seen:
                merged.append(item)
                seen.add(key)
        return merged

    def _finalize_missing(self, selected: list[CompanyCandidate], missing: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = list(missing)
        for index in range(max(0, self.input.top_x - len(selected))):
            result.append({"rank": len(selected) + index + 1, "missing_reason": "not enough valid recruitment urls"})
        return result

    @staticmethod
    def _looks_like_recruitment_url(url: str) -> bool:
        parsed = urlparse(unquote(url).lower())
        target = f"{parsed.netloc}{parsed.path}"
        hints = ("career", "careers", "job", "jobs", "talent", "recruit", "recruitment", "zhaopin", "campus", "graduate", "校招", "招聘")
        return any(hint in target for hint in hints)
