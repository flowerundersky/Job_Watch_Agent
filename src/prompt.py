"""Prompt builders for the second-version job-watch workflow."""

from __future__ import annotations

import json
from typing import Any


def build_company_selection_messages(job_role: str, top_x: int, company_filters: str = "") -> list[dict[str, str]]:
    filter_text = f"\n筛选条件：{company_filters}" if company_filters.strip() else ""
    return [
        {
            "role": "system",
            "content": (
                "你是一个根据岗位名称和筛选条件搜索公司网站的助手。"
                "我是一名快要毕业的大学生，想要了解哪些公司可能正在招聘某个岗位的员工和实习生，以及这些公司的招聘官网入口。"
                f"你的任务是根据岗位名称和筛选条件选出会发布此岗位的最多{top_x} 家公司和该公司的招聘官网入口。"
                f"recruitment_url里输出的是公司的招聘网站入口。只输出 JSON。最多返回{top_x}家；只返回你能给出招聘官网入口的公司；不足不要编造。"
                f"输出的格式：{{\"job_role\":\"...\",\"top_x\":{top_x},\"companies\":[{{\"name\":\"...\",\"recruitment_url\":\"https://...\"}}]}}"
                "不要返回第三方招聘平台、新闻稿、公众号文章、公司首页。"
                "最后达到的目标是帮助我快速锁定目标公司的招聘官网。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"岗位：{job_role}\n数量：{top_x}{filter_text}\n公司最好具备的条件：{company_filters}\n"
                f"请返回最可能发布“{job_role}”招聘信息的前 {top_x} 家公司及其官方招聘官网入口。"
            ),
        },
    ]


def build_company_selection_retry_message(
    job_role: str,
    top_x: int,
    current_companies: list[dict[str, Any]],
    company_filters: str = "",
) -> list[dict[str, str]]:
    filter_line = f"筛选条件：{company_filters}\n" if company_filters.strip() else ""
    missing_count = max(0, top_x - len(current_companies))
    return [
        {
            "role": "user",
            "content": (
                f"岗位：{job_role}\n"
                f"目标数量：{top_x}\n"
                f"还缺少：{missing_count} 家\n"
                f"{filter_line}"
                f"当前已返回公司数：{len(current_companies)}\n"
                f"当前结果：{json.dumps(current_companies, ensure_ascii=False, separators=(',', ':'))}\n"
                f"请补齐到恰好 {top_x} 家公司，不要重复已有公司，只输出新增部分。"
            ),
        }
    ]


def build_latest_date_messages(
    job_role: str,
    company_name: str,
    page_url: str,
    observation: dict[str, Any],
) -> list[dict[str, str]]:
    evidence = {
        "company": company_name,
        "page_url": page_url,
        "observation": observation,
    }
    return [
        {
            "role": "system",
            "content": (
                "你是一个在当前网页页面抓取招聘信息发布时间的agent。"
                "页面证据只包含渲染后的 observation，它是对 DOM 的轻量摘要；请依据 observation 的 headings、sections、interactive_elements 和 links 判断。"
                "你只做两件事：判断当前页是否足够提取招聘信息最新发布日期；如果不够，从当前页面证据里的链接中选下一跳。"
                "latest_posted_at 应尽量来自招聘公告、岗位列表、校招批次或实习生招聘相关内容。"
                "如果日期来源不清楚，不要强行判断；可以返回 is_sufficient=false 并选择更可能包含岗位列表或招聘公告的下一跳。"
                "next_hops 从 observation.links 或 observation.interactive_elements.href 中选择。"
                "只输出一个 JSON 对象，字段必须齐全；未知内容用空字符串、空数组或 low。"
                "{\"is_sufficient\":true|false,\"reason\":\"...\",\"next_hops\":[\"https://...\"],\"latest_company\":\"...\",\"latest_posted_at\":\"...\",\"confidence\":\"high|medium|low\"}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"岗位：{job_role}\n"
                f"页面证据：{json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))}\n"
                "如果当前证据足够，就返回 true 并输出 latest_posted_at；如果不够，就返回 false 并给出下一跳。"
            ),
        },
    ]


def build_channel_status_messages(
    job_role: str,
    company_name: str,
    page_url: str,
    observation: dict[str, Any],
) -> list[dict[str, str]]:
    evidence = {
        "company": company_name,
        "page_url": page_url,
        "observation": observation,
    }
    return [
        {
            "role": "system",
            "content": (
                "你是一个在当前网页页面寻找校园招聘通道的agent。"
                "页面证据只包含渲染后的 observation，它是对 DOM 的轻量摘要；请依据 observation 的 headings、sections、interactive_elements 和 links 判断。"
                "你只做两件事：判断当前页是否足以判断校园招聘通道状态；如果不够，从当前页面证据里的链接中选下一跳。"
                "open 表示页面能看出正在招聘、开放投递、存在有效岗位列表或投递入口。"
                "closed 表示页面能看出已结束、暂停招聘、暂无职位、未开放或停止投递。"
                "unknown 表示证据不足。不要因为只出现公司名、岗位名、日期或招聘字样就判断 open。"
                "next_hops 从 observation.links 或 observation.interactive_elements.href 中选择。"
                "只输出一个 JSON 对象，字段必须齐全；未知内容用 unknown、空数组或 low。"
                "{\"is_sufficient\":true|false,\"reason\":\"...\",\"next_hops\":[\"https://...\"],\"channel_status\":\"open|closed|unknown\",\"confidence\":\"high|medium|low\"}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"岗位：{job_role}\n"
                f"页面证据：{json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))}\n"
                "如果当前证据足够，就返回 true 并输出 channel_status；如果不够，就返回 false 并给出下一跳。"
            ),
        },
    ]


def extract_json_object(raw_text: str) -> dict[str, Any]:
    """Extract a JSON object from a model response."""

    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("model response does not contain a JSON object")

    return json.loads(text[start : end + 1])
