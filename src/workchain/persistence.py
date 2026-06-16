"""Workflow output rendering and persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..models import AnalysisResult, CompanyCandidate, CrawledPage, WorkflowResult
from .formatters import compact_candidate, compact_page, status_display


def write_outputs(config: AppConfig, result: WorkflowResult) -> None:
    selected_companies = [compact_candidate(candidate) for candidate in result.selected_companies]
    crawled_pages = [compact_page(page) for page in result.crawled_pages]
    analysis_payload = analysis_to_payload(result.analysis)
    metadata_payload = {
        "job_role": result.job_role,
        "top_x": result.top_x,
        "summary": result.summary,
    }
    selection_payload = {
        "selected_companies": selected_companies,
        "missing_companies": result.missing_companies,
    }
    crawl_payload = {
        "pages": crawled_pages,
    }
    paths_payload = {
        "report_path": result.report_path,
        "result_path": result.result_path,
        "snapshot_path": result.snapshot_path,
        "trace_path": str(config.trace_path),
    }
    snapshot_payload = {
        "metadata": metadata_payload,
        "selection": selection_payload,
        "crawl": crawl_payload,
        "analysis": analysis_payload,
        "changes": result.changes,
        "paths": paths_payload,
        "structure_note": "selection=公司筛选结果; crawl=爬取页面结果; analysis=最终判断",
        # Backward-compatible top-level fields.
        "job_role": result.job_role,
        "top_x": result.top_x,
        "selected_companies": selected_companies,
        "missing_companies": result.missing_companies,
        "crawled_pages": crawled_pages,
    }
    payload = build_result_payload(result.selected_companies, result.crawled_pages)
    Path(result.result_path).parent.mkdir(parents=True, exist_ok=True)
    Path(result.snapshot_path).parent.mkdir(parents=True, exist_ok=True)
    Path(result.report_path).parent.mkdir(parents=True, exist_ok=True)
    config.trace_path.parent.mkdir(parents=True, exist_ok=True)
    Path(result.result_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    Path(result.snapshot_path).write_text(
        json.dumps(snapshot_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    Path(result.report_path).write_text(render_markdown(result), encoding="utf-8")
    config.trace_path.write_text(render_trace_markdown(result), encoding="utf-8")


def write_selection_output(
    config: AppConfig,
    selected_candidates: list[CompanyCandidate],
    missing_candidates: list[dict[str, Any]],
) -> None:
    config.selection_path.parent.mkdir(parents=True, exist_ok=True)
    config.selection_path.write_text(
        json.dumps(
            {
                "selection": {
                    "selected_companies": [compact_candidate(candidate) for candidate in selected_candidates],
                },
                "missing": missing_candidates,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def analysis_to_payload(analysis: AnalysisResult) -> dict[str, str]:
    return {
        "job_role": analysis.job_role,
        "period_company": analysis.period_company,
        "recruitment_period": analysis.recruitment_period,
        "application_start": analysis.application_start,
        "application_deadline": analysis.application_deadline,
        "period_evidence": analysis.period_evidence,
        "latest_company": analysis.latest_company,
        "latest_posted_at": analysis.latest_posted_at,
        "channel_status": analysis.channel_status,
        "confidence": analysis.confidence,
    }


def build_result_payload(
    selected_companies: list[CompanyCandidate],
    crawled_pages: list[CrawledPage],
) -> dict[str, Any]:
    pages_by_company: dict[str, dict[str, Any]] = {}
    for page in crawled_pages:
        key = page.company.strip().lower()
        record = pages_by_company.setdefault(
            key,
            {
                "company": page.company,
                "website": "",
                "recruitment_period": "",
                "application_start": "",
                "application_deadline": "",
                "period_evidence": "",
                "latest_posted_at": "",
                "channel_status": "unknown",
            },
        )
        if page.page_url and not record["website"]:
            record["website"] = page.page_url
        if page.recruitment_period and not record["recruitment_period"]:
            record["recruitment_period"] = page.recruitment_period
        if page.application_start and not record["application_start"]:
            record["application_start"] = page.application_start
        if page.application_deadline and not record["application_deadline"]:
            record["application_deadline"] = page.application_deadline
        if page.period_evidence and not record["period_evidence"]:
            record["period_evidence"] = page.period_evidence
        if page.latest_posted_at and not record["latest_posted_at"]:
            record["latest_posted_at"] = page.latest_posted_at
        if page.channel_status in {"open", "closed"}:
            record["channel_status"] = page.channel_status

    companies: list[dict[str, Any]] = []
    for candidate in selected_companies:
        key = candidate.name.strip().lower()
        record = pages_by_company.get(
            key,
            {
                "company": candidate.name,
                "website": candidate.recruitment_url,
                "recruitment_period": "",
                "application_start": "",
                "application_deadline": "",
                "period_evidence": "",
                "latest_posted_at": "",
                "channel_status": "unknown",
            },
        )
        if not record.get("website"):
            record = {**record, "website": candidate.recruitment_url}
        companies.append(
            {
                "company": record.get("company", candidate.name),
                "website": record.get("website", candidate.recruitment_url),
                "recruitment_period": record.get("recruitment_period", ""),
                "application_start": record.get("application_start", ""),
                "application_deadline": record.get("application_deadline", ""),
                "period_evidence": record.get("period_evidence", ""),
                "latest_posted_at": record.get("latest_posted_at", ""),
                "channel_status": record.get("channel_status", "unknown"),
            }
        )

    return {
        "companies": companies,
    }


def render_trace_markdown(result: WorkflowResult) -> str:
    pages_by_company: dict[str, list[CrawledPage]] = {}
    for page in result.crawled_pages:
        pages_by_company.setdefault(page.company, []).append(page)

    lines = [
        "# Job Watch Trace",
        "",
        f"- 岗位：{result.job_role}",
        f"- 公司数：{result.top_x}",
        "",
        "## 筛选公司",
        "",
        "| 排名 | 公司 | 招聘官网入口 |",
        "| --- | --- | --- |",
    ]
    for candidate in result.selected_companies:
        lines.append(f"| {candidate.rank} | {candidate.name} | {candidate.recruitment_url} |")

    for candidate in result.selected_companies:
        lines.extend(["", f"## {candidate.rank}. {candidate.name}", "", f"- 筛选网址：{candidate.recruitment_url}"])
        company_pages = pages_by_company.get(candidate.name, [])
        if not company_pages:
            lines.append("- 没有抓取记录")
            continue
        for task_type in ("period", "channel"):
            task_pages = [page for page in company_pages if page.task_type == task_type]
            if not task_pages:
                continue
            task_label = "招聘时间段 agent" if task_type == "period" else "通道状态 agent"
            lines.extend(["", f"### {task_label}"])
            trace_steps = task_pages[-1].trace_steps
            if not trace_steps:
                lines.append("- 没有链路明细")
                continue
            for step in trace_steps:
                lines.extend(render_trace_step(step))

    return "\n".join(lines) + "\n"


def render_trace_step(step: dict[str, Any]) -> list[str]:
    task_type = str(step.get("task_type", ""))
    decision = step.get("decision") if isinstance(step.get("decision"), dict) else {}
    observation = step.get("observation") if isinstance(step.get("observation"), dict) else {}
    next_hops = step.get("next_hops") if isinstance(step.get("next_hops"), list) else []
    action_chain = step.get("action_chain") if isinstance(step.get("action_chain"), list) else []
    lines = [
        "",
        f"#### 第 {step.get('hop_index', '')} 跳",
        "",
        f"- 请求网址：{step.get('requested_url', '')}",
        f"- 实际页面：{step.get('page_url', '')}",
        f"- 页面标题：{step.get('title', '') or observation.get('title', '') or '未提取'}",
        f"- 是否足够：{'是' if step.get('is_sufficient') else '否'}",
        f"- 选择目标：{step.get('selected_action_type', '') or '无'} / {step.get('selected_menu', '') or '无'}",
        f"- 点击后 URL：{', '.join(str(item) for item in next_hops) if next_hops else '无'}",
    ]
    if action_chain:
        lines.extend(["", "Hover/点击链路：", "", "```json", json.dumps(action_chain, ensure_ascii=False, indent=2), "```"])
    if step.get("error"):
        lines.append(f"- 抓取错误：{step.get('error')}")

    lines.extend(
        [
            "",
            "DOM 轻量化抽取：",
            "",
            "```json",
            json.dumps(compact_observation_for_trace(observation), ensure_ascii=False, indent=2),
            "```",
            "",
            "模型原始输出：",
            "",
            "```json",
            format_raw_model_output(str(step.get("raw_model_output", ""))),
            "```",
            "",
            "模型解析结果：",
            "",
            "```json",
            json.dumps(decision, ensure_ascii=False, indent=2),
            "```",
        ]
    )
    if task_type == "period":
        period = str(decision.get("recruitment_period") or step.get("recruitment_period") or "")
        deadline = str(decision.get("application_deadline") or step.get("application_deadline") or "")
        evidence = str(decision.get("period_evidence") or step.get("period_evidence") or "")
        lines.append(f"- 招聘时间段：{period or '未提取'}")
        lines.append(f"- 投递截止：{deadline or '未提取'}")
        if evidence:
            lines.append(f"- 时间证据：{evidence}")
    elif task_type == "channel":
        lines.append(f"- 通道状态：{status_display(str(decision.get('channel_status', 'unknown')))}")
    return lines


def compact_observation_for_trace(observation: dict[str, Any]) -> dict[str, Any]:
    sections = observation.get("sections") if isinstance(observation.get("sections"), list) else []
    menus = observation.get("menus") if isinstance(observation.get("menus"), list) else []
    actions = observation.get("actions") if isinstance(observation.get("actions"), list) else []
    content = str(observation.get("content") or observation.get("visible_text_excerpt") or "")
    return {
        "page_url": observation.get("page_url", ""),
        "title": observation.get("title", ""),
        "headings": observation.get("headings", [])[:10] if isinstance(observation.get("headings"), list) else [],
        "content": content[:800],
        "sections": sections[:5],
        "menus": menus[:12],
        "actions": actions[:12],
    }


def format_raw_model_output(raw_output: str) -> str:
    raw_output = raw_output.strip()
    if not raw_output:
        return "{}"
    try:
        return json.dumps(json.loads(raw_output), ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        return raw_output


def render_markdown(result: WorkflowResult) -> str:
    lines = [
        "# Job Watch Report",
        "",
        f"- 岗位：{result.job_role}",
        f"- 公司数：{result.top_x}",
        f"- 招聘时间公司：{result.analysis.period_company or '未识别'}",
        f"- 招聘时间段：{result.analysis.recruitment_period or '未识别'}",
        f"- 投递开始：{result.analysis.application_start or '未识别'}",
        f"- 投递截止：{result.analysis.application_deadline or '未识别'}",
        f"- 通道状态：{status_display(result.analysis.channel_status)}",
        f"- 置信度：{result.analysis.confidence}",
        "",
        "## 公司",
    ]
    for candidate in result.selected_companies:
        lines.append(f"- {candidate.rank}. {candidate.name} | {candidate.recruitment_url}")

    lines.extend(["", "## 页面"])
    for page in result.crawled_pages:
        lines.append(f"- {page.company} | {page.page_url} | {page.site_type} | {status_display(page.channel_status)}")
        if page.recruitment_period:
            lines.append(f"  - 招聘时间段：{page.recruitment_period}")
        if page.application_deadline:
            lines.append(f"  - 投递截止：{page.application_deadline}")
        if page.period_evidence:
            lines.append(f"  - 时间证据：{page.period_evidence}")
        if page.error:
            lines.append(f"  - 错误：{page.error}")

    lines.extend(["", "## 变化"])
    if result.changes.get("has_previous"):
        lines.append("- 有历史快照：是")
        lines.append(f"- 招聘时间段是否变化：{ '是' if result.changes.get('period_changed') else '否' }")
        lines.append(f"- 投递截止是否变化：{ '是' if result.changes.get('deadline_changed') else '否' }")
        lines.append(f"- 通道状态是否变化：{ '是' if result.changes.get('status_changed') else '否' }")
        for item in result.changes.get("updated_companies", []):
            lines.append(
                f"- {item.get('company', '')} | "
                f"{item.get('previous_period', '') or '未识别'} -> {item.get('current_period', '') or '未识别'} | "
                f"{status_display(str(item.get('previous_status', 'unknown')))} -> {status_display(str(item.get('current_status', 'unknown')))}"
            )
    else:
        lines.append("- 无历史快照")

    lines.extend(["", "## 结果", result.summary])
    return "\n".join(lines) + "\n"
