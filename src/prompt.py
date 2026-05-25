"""Prompt builders for the second-version job-watch workflow."""

from __future__ import annotations

import json
from typing import Any


def build_company_selection_messages(job_role: str, top_x: int) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                f"根据岗位名称选出最可能发布此岗位的 {top_x} 家公司和官网入口。只输出 JSON。"
                f"格式：{{\"job_role\":\"...\",\"top_x\":{top_x},\"companies\":[{{\"rank\":1,\"name\":\"...\",\"recruitment_url\":\"https://...\"}}]}}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"岗位：{job_role}\n数量：{top_x}\n"
                f"请返回最可能发布“{job_role}”招聘信息的前 {top_x} 家公司及其官网入口。"
            ),
        },
    ]


def build_company_selection_retry_message(
    job_role: str,
    top_x: int,
    current_companies: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {
            "role": "user",
            "content": (
                f"岗位：{job_role}\n"
                f"目标数量：{top_x}\n"
                f"当前已返回公司数：{len(current_companies)}\n"
                f"当前结果：{json.dumps(current_companies, ensure_ascii=False, separators=(',', ':'))}\n"
                f"请补齐到恰好 {top_x} 家公司，不要重复已有公司，只输出新增部分。"
            ),
        }
    ]


def build_analysis_messages(
    job_role: str,
    selected_companies: list[dict[str, Any]],
    crawled_pages: list[dict[str, Any]],
) -> list[dict[str, str]]:

    def _compact_company(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "n": str(item.get("name") or item.get("company") or "").strip(),
            "u": str(item.get("recruitment_url") or item.get("url") or "").strip(),
        }

    def _compact_page(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "c": str(item.get("company") or "").strip(),
            "u": str(item.get("page_url") or item.get("recruitment_url") or "").strip(),
            "d": list(item.get("date_candidates") or [])[:3],
            "s": str(item.get("site_type") or "").strip(),
            "t": str(item.get("channel_status") or "").strip(),
            "e": str(item.get("error") or "").strip(),
        }

    compact_companies = [_compact_company(item) for item in selected_companies]
    compact_pages = [_compact_page(item) for item in crawled_pages]

    return [
        {
            "role": "system",
            "content": (
                "根据抓取结果判断最近一次招聘发布时间和通道状态。不要补充未抓取到的信息，不要臆造。"
                "只输出 JSON："
                "{\"job_role\":\"...\",\"latest_company\":\"...\",\"latest_posted_at\":\"...\",\"channel_status\":\"open|closed|unknown\",\"confidence\":\"high|medium|low\"}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"岗位：{job_role}\n"
                f"公司：{json.dumps(compact_companies, ensure_ascii=False, separators=(',', ':'))}\n"
                f"页面：{json.dumps(compact_pages, ensure_ascii=False, separators=(',', ':'))}"
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
