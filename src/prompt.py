"""Prompt builders for the second-version job-watch workflow."""

from __future__ import annotations

import json
from typing import Any


def build_company_selection_messages(job_role: str, top_x: int) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是招聘情报分析助手。你的任务是根据岗位名称，推断最可能发布此岗位招聘信息的公司，"
                "并给出这些公司的官方招聘官网或招聘入口。"
                "只输出 JSON，不要输出解释、不要输出 markdown、不要输出代码块。"
                "返回结构必须是："
                "{\"job_role\": \"...\", \"top_x\": 3, \"companies\": ["
                "{\"rank\": 1, \"name\": \"...\", \"recruitment_url\": \"https://...\", \"reason\": \"...\"}]}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"岗位：{job_role}\n"
                f"数量：{top_x}\n"
                f"请输出最可能发布“{job_role}”招聘信息的前 {top_x} 家公司及其官方招聘官网。"
                "每一项都必须包含公司名、招聘官网和简短原因。"
            ),
        },
    ]


def build_analysis_messages(
    job_role: str,
    selected_companies: list[dict[str, Any]],
    crawled_pages: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是招聘发布时间分析助手。你只能使用我提供的抓取结果，不要补充未抓取到的信息，"
                "也不要臆造发布日期。你的任务是判断最近一次招聘信息是什么时候发布的。"
                "只输出 JSON，不要输出解释、不要输出 markdown、不要输出代码块。"
                "返回结构必须是："
                "{\"job_role\": \"...\", \"latest_company\": \"...\", \"latest_posted_at\": \"...\", "
                "\"evidence\": \"...\", \"summary\": \"...\", \"confidence\": \"high|medium|low\"}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"岗位：{job_role}\n\n"
                f"第一阶段公司结果：\n{json.dumps(selected_companies, ensure_ascii=False, indent=2)}\n\n"
                f"抓取到的招聘页面：\n{json.dumps(crawled_pages, ensure_ascii=False, indent=2)}\n\n"
                "请判断最近一次招聘信息的发布时间，并说明你依据的是哪一家公司的哪一条抓取结果。"
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
