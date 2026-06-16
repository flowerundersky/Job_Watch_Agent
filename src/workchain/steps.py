"""Reusable workflow step functions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..agents.channel_status import ChannelStatusAgent
from ..agents.recruitment_period import RecruitmentPeriodAgent
from ..agents.selection import CompanySelectionAgent
from ..models import CompanyCandidate, CrawledPage, WorkflowResult
from .analysis import build_summary, combine_agent_results
from .changes import build_changes
from .persistence import write_outputs, write_selection_output
from .state import WorkflowContext, WorkflowState


def select_companies_with_missing(context: WorkflowContext) -> dict[str, Any]:
    """调用公司筛选 agent，保留成功项和缺失/非法项，便于排查。"""
    return CompanySelectionAgent(
        context.backend,
        job_role=context.config.job_role,
        top_x=context.config.top_x,
        company_filters=context.config.company_filters,
    ).run()


def select_companies(context: WorkflowContext) -> list[CompanyCandidate]:
    return select_companies_with_missing(context)["selected"]


def graph_select_companies(context: WorkflowContext, state: WorkflowState) -> dict[str, Any]:
    """第一步：让筛选 agent 产出目标公司和招聘官网入口。"""
    selection = select_companies_with_missing(context)
    write_selection_output(context.config, selection["selected"], selection["missing"])
    print("公司筛选已完成")
    return {
        "selected_candidates": selection["selected"],
        "missing_candidates": selection["missing"],
    }


def graph_crawl_pages(context: WorkflowContext, state: WorkflowState) -> dict[str, Any]:
    """第二步：并行运行时间 agent 和通道 agent 的页面探索流程。"""
    selected_candidates = state["selected_candidates"]
    print("开始抓取页面")
    with ThreadPoolExecutor(max_workers=2) as executor:
        date_future = executor.submit(crawl_time_pages, context, selected_candidates)
        channel_future = executor.submit(crawl_channel_pages, context, selected_candidates)
        date_pages = date_future.result()
        channel_pages = channel_future.result()
    return {
        "date_crawled_pages": date_pages,
        "channel_crawled_pages": channel_pages,
    }


def graph_analyze(context: WorkflowContext, state: WorkflowState) -> dict[str, Any]:
    """第三步：把两个 agent 的页面级判断合并成一个总分析结果。"""
    date_pages = state.get("date_crawled_pages", [])
    channel_pages = state.get("channel_crawled_pages", [])
    analysis = combine_agent_results(context.config.job_role, date_pages, channel_pages)
    return {"analysis": analysis}


def graph_persist(context: WorkflowContext, state: WorkflowState) -> dict[str, Any]:
    """第四步：生成报告、JSON、快照和 trace 文件。"""
    selected_candidates = state["selected_candidates"]
    missing_candidates = state.get("missing_candidates", [])
    date_pages = state.get("date_crawled_pages", [])
    channel_pages = state.get("channel_crawled_pages", [])
    crawled_pages = [*date_pages, *channel_pages]
    analysis = state["analysis"]
    changes = build_changes(context.config.snapshot_path, crawled_pages, analysis)
    result = WorkflowResult(
        job_role=context.config.job_role,
        top_x=context.config.top_x,
        selected_companies=selected_candidates,
        missing_companies=missing_candidates,
        crawled_pages=crawled_pages,
        analysis=analysis,
        report_path=str(context.config.report_path),
        result_path=str(context.config.result_path),
        snapshot_path=str(context.config.snapshot_path),
        summary=build_summary(context.config.job_role, selected_candidates, crawled_pages, analysis),
        changes=changes,
    )

    write_outputs(context.config, result)
    print("结果已生成")
    return {"result": result, "changes": changes}


def crawl_time_pages(context: WorkflowContext, candidates: list[CompanyCandidate]) -> list[CrawledPage]:
    """运行专门判断官方招聘时间段的页面探索 agent。"""
    agent = RecruitmentPeriodAgent(context.backend, job_role=context.config.job_role, runtime=context.config.runtime)
    return [agent.run(candidate) for candidate in candidates]


def crawl_channel_pages(context: WorkflowContext, candidates: list[CompanyCandidate]) -> list[CrawledPage]:
    """运行专门判断招聘通道 open/closed/unknown 的页面探索 agent。"""
    agent = ChannelStatusAgent(context.backend, job_role=context.config.job_role, runtime=context.config.runtime)
    return [agent.run(candidate) for candidate in candidates]
