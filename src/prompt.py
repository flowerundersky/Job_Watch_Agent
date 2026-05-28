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
                "只要总招聘页，不要返回校招专门页，第三方招聘平台、新闻稿、公众号文章、公司首页、岗位列表页。"
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


def build_recruitment_period_messages(
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


def build_latest_date_messages(
    job_role: str,
    company_name: str,
    page_url: str,
    observation: dict[str, Any],
) -> list[dict[str, str]]:
    return build_recruitment_period_messages(job_role, company_name, page_url, observation)


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


def build_click_target_messages(
    task_type: str,
    company_name: str,
    parent_target: dict[str, str],
    hover_targets: list[dict[str, str]],
) -> list[dict[str, str]]:
    task_label = "招聘时间段" if task_type == "period" else "校园招聘通道状态"
    evidence = {
        "company": company_name,
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
        {
            "role": "user",
            "content": f"悬停证据：{json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))}",
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
