"""Job-watch workflow orchestration."""

from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from .config import AppConfig
from .model import create_backend
from .models import CompanyCandidate, WorkflowResult
from .workchain.state import WorkflowContext, WorkflowState
from .workchain.steps import (
    graph_analyze,
    graph_crawl_pages,
    graph_persist,
    graph_select_companies,
    select_companies,
    select_companies_with_missing,
)


class JobWatchWorkflow:
    """主工作流编排器：串起公司筛选、页面探索、结果合并和文件输出。"""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.backend = create_backend(config.model_backend)
        self.context = WorkflowContext(config=config, backend=self.backend)
        self.graph = self._build_graph()

    def run(self) -> WorkflowResult:
        """运行一次完整任务，并返回最终结构化结果。"""
        self.config.runtime.output_dir.mkdir(parents=True, exist_ok=True)
        self._sync_context()
        final_state = self.graph.invoke({})
        return final_state["result"]

    def _build_graph(self) -> Any:
        """定义 LangGraph 节点顺序：筛公司 -> 爬页面 -> 分析 -> 落盘。"""
        graph = StateGraph(WorkflowState)
        graph.add_node("select_companies", partial(graph_select_companies, self.context))
        graph.add_edge(START, "select_companies")
        graph.add_edge("select_companies", END)
        return graph.compile()

    def _select_companies(self) -> list[CompanyCandidate]:
        self._sync_context()
        return select_companies(self.context)

    def _select_companies_with_missing(self) -> dict[str, Any]:
        """Compatibility helper used by tests and one-off stage debugging."""
        self._sync_context()
        return select_companies_with_missing(self.context)

    def _sync_context(self) -> None:
        self.context.config = self.config
        self.context.backend = self.backend
