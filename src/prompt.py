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
                f"你是一个根据岗位名称和筛选条件搜索公司网站的助手。"
                f"我是一名快要毕业的大学生，想要了解哪些公司可能正在招聘某个岗位的员工和实习生，以及这些公司的招聘官网入口。"
                f"你的任务是根据岗位名称和筛选条件选出会发布此岗位的 {top_x} 家公司和该公司的招聘官网入口。"
                f"recruitment_url里输出的是公司的招聘网站入口。只输出 JSON。只输出恰好 {top_x} 家公司的信息。如果找不到足够的公司，返回空数组，不要编造。"
                f"输出的格式：{{\"job_role\":\"...\",\"top_x\":{top_x},\"companies\":[{{\"name\":\"...\",\"recruitment_url\":\"https://...\"}}]}}"
                f"最后达到的目标是帮助我快速锁定目标公司的招聘官网。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"岗位：{job_role}\n数量：{top_x}{filter_text}\n公司最好具备的条件：{company_filters}\n"
                f"请返回最可能发布“{job_role}”招聘信息的前 {top_x} 家公司及其招聘官网入口。"
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
    title: str,
    text: str,
    links: list[str],
) -> list[dict[str, str]]:
    evidence = {
        "company": company_name,
        "page_url": page_url,
        "title": title,
        "text": text[:2400],
        "links": links[:20],
    }
    return [
        {
            "role": "system",
            "content": (
                "你是时间 agent。你只做两件事：判断当前页面是否足够提取最新发布日期；不够就从给定 links 里选下一跳。"
                "只依据当前页面已经出现的信息，不跳出给定 links。只输出 JSON："
                "{\"is_sufficient\":true|false,\"reason\":\"...\",\"next_hops\":[\"https://...\"],\"latest_company\":\"...\",\"latest_posted_at\":\"...\",\"confidence\":\"high|medium|low\"}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"岗位：{job_role}\n"
                f"页面证据：{json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))}\n"
                "没有明确日期就返回 false 和下一跳；有明确日期就返回 true 并输出 latest_posted_at。"
            ),
        },
    ]


def build_channel_status_messages(
    job_role: str,
    company_name: str,
    page_url: str,
    title: str,
    text: str,
    links: list[str],
) -> list[dict[str, str]]:
    evidence = {
        "company": company_name,
        "page_url": page_url,
        "title": title,
        "text": text[:2400],
        "links": links[:20],
    }
    return [
        {
            "role": "system",
            "content": (
                "你是通道 agent。"
                "你只做两件事：判断当前页面是否足以判断校园招聘通道；不够就从给定 links 里选下一跳。"
                "只能依据页面里明确出现的开放或关闭信号判断，不能因为有日期、岗位名称或公司名就推断开启。只输出 JSON："
                "{\"is_sufficient\":true|false,\"reason\":\"...\",\"next_hops\":[\"https://...\"],\"channel_status\":\"open|closed|unknown\",\"confidence\":\"high|medium|low\"}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"岗位：{job_role}\n"
                f"页面证据：{json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))}\n"
                "如果当前页面没有明确开放或关闭信号，就把 is_sufficient 设为 false，并只从 links 里返回下一跳；"
                "如果有明确证据，就把 is_sufficient 设为 true，并只输出当前页面里能明确支持的 channel_status。"
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
