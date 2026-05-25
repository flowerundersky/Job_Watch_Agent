"""Second-version job-watch workflow orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .config import AppConfig
from .crawler import crawl_company_pages
from .model import OpenAICompatibleBackend, analyze_latest_posting, create_backend
from .models import AnalysisResult, CompanyCandidate, CrawledPage, WorkflowResult
from .prompt import build_analysis_messages, build_company_selection_messages, build_company_selection_retry_message, extract_json_object


class WorkflowState(TypedDict, total=False):
    selected_candidates: list[CompanyCandidate]
    crawled_pages: list[CrawledPage]
    analysis: AnalysisResult
    changes: dict[str, Any]
    result: WorkflowResult


class JobWatchWorkflow:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.backend = create_backend(config.model_backend)
        self.graph = self._build_graph()

    def run(self) -> WorkflowResult:
        self.config.runtime.output_dir.mkdir(parents=True, exist_ok=True)

        final_state = self.graph.invoke({})
        result = final_state["result"]
        return result

    def _build_graph(self) -> Any:
        graph = StateGraph(WorkflowState)
        graph.add_node("select_companies", self._graph_select_companies)
        graph.add_node("crawl_pages", self._graph_crawl_pages)
        graph.add_node("analyze", self._graph_analyze)
        graph.add_node("persist", self._graph_persist)
        graph.add_edge(START, "select_companies")
        graph.add_edge("select_companies", "crawl_pages")
        graph.add_edge("crawl_pages", "analyze")
        graph.add_edge("analyze", "persist")
        graph.add_edge("persist", END)
        return graph.compile()

    def _graph_select_companies(self, state: WorkflowState) -> dict[str, Any]:
        selected_candidates = self._select_companies()
        self._write_selection_output(selected_candidates)
        return {"selected_candidates": selected_candidates}

    def _graph_crawl_pages(self, state: WorkflowState) -> dict[str, Any]:
        selected_candidates = state["selected_candidates"]
        crawled_pages = crawl_company_pages(
            selected_candidates,
            timeout_seconds=self.config.runtime.timeout_seconds,
            max_crawl_chars=self.config.runtime.max_crawl_chars,
            max_links_per_page=self.config.runtime.max_links_per_page,
        )
        return {"crawled_pages": crawled_pages}

    def _graph_analyze(self, state: WorkflowState) -> dict[str, Any]:
        selected_candidates = state["selected_candidates"]
        crawled_pages = state["crawled_pages"]
        analysis = self._analyze_latest_posting(selected_candidates, crawled_pages)
        return {"analysis": analysis}

    def _graph_persist(self, state: WorkflowState) -> dict[str, Any]:
        selected_candidates = state["selected_candidates"]
        crawled_pages = state["crawled_pages"]
        analysis = state["analysis"]
        changes = self._build_changes(crawled_pages, analysis)
        result = WorkflowResult(
            job_role=self.config.job_role,
            top_x=self.config.top_x,
            selected_companies=selected_candidates,
            crawled_pages=crawled_pages,
            analysis=analysis,
            report_path=str(self.config.report_path),
            result_path=str(self.config.result_path),
            snapshot_path=str(self.config.snapshot_path),
            summary=self._build_summary(selected_candidates, crawled_pages, analysis),
            changes=changes,
        )

        self._write_outputs(result)
        return {"result": result, "changes": changes}

    def _select_companies(self) -> list[CompanyCandidate]:
        messages = build_company_selection_messages(
            self.config.job_role,
            self.config.top_x,
            self.config.company_filters,
        )
        raw_output = self.backend.chat(messages)
        payload = extract_json_object(raw_output)
        candidates = self._parse_company_candidates(payload)

        attempts = 0
        while len(candidates) < self.config.top_x and attempts < 2:
            attempts += 1
            current_payload = [candidate.to_dict() for candidate in candidates]
            messages = messages + [
                {"role": "assistant", "content": raw_output},
                *build_company_selection_retry_message(
                    self.config.job_role,
                    self.config.top_x,
                    current_payload,
                    self.config.company_filters,
                ),
            ]
            raw_output = self.backend.chat(messages)
            payload = extract_json_object(raw_output)
            candidates = self._merge_company_candidates(candidates, self._parse_company_candidates(payload))

        if len(candidates) < self.config.top_x:
            raise ValueError(
                f"company selection returned only {len(candidates)} candidates, expected {self.config.top_x}"
            )

        return candidates[: self.config.top_x]

    def _analyze_latest_posting(
        self,
        selected_companies: list[CompanyCandidate],
        crawled_pages: list[CrawledPage],
    ) -> AnalysisResult:
        if isinstance(self.backend, OpenAICompatibleBackend):
            raw_output = self.backend.chat(
                build_analysis_messages(
                    self.config.job_role,
                    [candidate.to_dict() for candidate in selected_companies],
                    [page.to_dict() for page in crawled_pages],
                )
            )
            payload = extract_json_object(raw_output)
            analysis = AnalysisResult(
                job_role=str(payload.get("job_role", self.config.job_role)),
                latest_company=str(payload.get("latest_company", "")),
                latest_posted_at=str(payload.get("latest_posted_at", "")),
                channel_status=str(payload.get("channel_status", "unknown")),
                confidence=str(payload.get("confidence", "low")),
            )
            return analysis

        analysis = analyze_latest_posting(self.config.job_role, selected_companies, crawled_pages)
        return analysis

    def _parse_company_candidates(self, payload: dict[str, Any]) -> list[CompanyCandidate]:
        raw_companies = payload.get("companies", [])
        if not isinstance(raw_companies, list):
            raise ValueError("company selection output missing companies list")

        candidates: list[CompanyCandidate] = []
        for index, item in enumerate(raw_companies, start=1):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("company") or "").strip()
            recruitment_url = str(
                item.get("recruitment_url")
                or item.get("url")
                or item.get("career_url")
                or item.get("careers_url")
                or ""
            ).strip()
            if not name or not recruitment_url:
                continue
            candidates.append(
                CompanyCandidate(
                    rank=int(item.get("rank") or index),
                    name=name,
                    recruitment_url=recruitment_url,
                    reason=str(item.get("reason") or "").strip(),
                    raw=item,
                )
            )

        if not candidates:
            raise ValueError("company selection output did not return usable candidates")

        return candidates

    def _merge_company_candidates(
        self,
        existing: list[CompanyCandidate],
        new_items: list[CompanyCandidate],
    ) -> list[CompanyCandidate]:
        merged: list[CompanyCandidate] = list(existing)
        seen_keys = {
            (candidate.name.strip().lower(), candidate.recruitment_url.strip().lower())
            for candidate in merged
        }
        for candidate in new_items:
            key = (candidate.name.strip().lower(), candidate.recruitment_url.strip().lower())
            if key in seen_keys:
                continue
            merged.append(candidate)
            seen_keys.add(key)
        for index, candidate in enumerate(merged, start=1):
            candidate.rank = index
        return merged

    def _build_summary(
        self,
        selected_candidates: list[CompanyCandidate],
        crawled_pages: list[CrawledPage],
        analysis: AnalysisResult,
    ) -> str:
        return (
            f"job={self.config.job_role}; companies={len(selected_candidates)}; "
            f"latest={analysis.latest_posted_at or '未识别'}; status={self._status_display(analysis.channel_status)}"
        )

    def _build_changes(self, crawled_pages: list[CrawledPage], analysis: AnalysisResult) -> dict[str, Any]:
        current_snapshot = self._snapshot_payload(crawled_pages, analysis)
        previous_snapshot = self._load_previous_snapshot()
        if not previous_snapshot:
            return {"has_previous": False, "updated": False, "status_changed": False}

        previous_pages = {
            str(item.get("company") or "").strip().lower(): item
            for item in previous_snapshot.get("crawled_pages", [])
            if isinstance(item, dict)
        }
        updated_companies: list[dict[str, Any]] = []
        for page in current_snapshot["crawled_pages"]:
            previous_page = previous_pages.get(str(page.get("company") or "").strip().lower())
            if not previous_page:
                continue
            if page.get("date") != previous_page.get("date") or page.get("channel_status") != previous_page.get("channel_status"):
                updated_companies.append(
                    {
                        "company": page.get("company", ""),
                        "previous_date": previous_page.get("date", []),
                        "current_date": page.get("date", []),
                        "previous_status": previous_page.get("channel_status", "unknown"),
                        "current_status": page.get("channel_status", "unknown"),
                    }
                )

        latest_changed = previous_snapshot.get("analysis", {}).get("latest_posted_at") != analysis.latest_posted_at
        status_changed = previous_snapshot.get("analysis", {}).get("channel_status") != analysis.channel_status
        return {
            "has_previous": True,
            "updated": bool(updated_companies or latest_changed),
            "status_changed": status_changed,
            "latest_changed": latest_changed,
            "updated_companies": updated_companies,
        }

    def _snapshot_payload(self, crawled_pages: list[CrawledPage], analysis: AnalysisResult) -> dict[str, Any]:
        return {
            "job_role": self.config.job_role,
            "top_x": self.config.top_x,
            "selected_companies": [],
            "crawled_pages": [self._compact_page(page) for page in crawled_pages],
            "analysis": {
                "job_role": analysis.job_role,
                "latest_company": analysis.latest_company,
                "latest_posted_at": analysis.latest_posted_at,
                "channel_status": analysis.channel_status,
                "confidence": analysis.confidence,
            },
        }

    def _load_previous_snapshot(self) -> dict[str, Any]:
        path = self.config.snapshot_path
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_outputs(self, result: WorkflowResult) -> None:
        snapshot_payload = {
            "job_role": result.job_role,
            "top_x": result.top_x,
            "selected_companies": [self._compact_candidate(candidate) for candidate in result.selected_companies],
            "crawled_pages": [self._compact_page(page) for page in result.crawled_pages],
            "analysis": {
                "job_role": result.analysis.job_role,
                "latest_company": result.analysis.latest_company,
                "latest_posted_at": result.analysis.latest_posted_at,
                "channel_status": result.analysis.channel_status,
                "confidence": result.analysis.confidence,
            },
            "changes": result.changes,
        }
        payload = {
            "job_role": result.job_role,
            "top_x": result.top_x,
            "selected_companies": [self._compact_candidate(candidate) for candidate in result.selected_companies],
            "crawled_pages": [self._compact_page(page) for page in result.crawled_pages],
            "analysis": {
                "job_role": result.analysis.job_role,
                "latest_company": result.analysis.latest_company,
                "latest_posted_at": result.analysis.latest_posted_at,
                "channel_status": result.analysis.channel_status,
                "confidence": result.analysis.confidence,
            },
            "report_path": result.report_path,
            "result_path": result.result_path,
            "snapshot_path": result.snapshot_path,
            "summary": result.summary,
            "changes": result.changes,
            "error": result.error,
        }
        Path(result.result_path).parent.mkdir(parents=True, exist_ok=True)
        Path(result.snapshot_path).parent.mkdir(parents=True, exist_ok=True)
        Path(result.report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(result.result_path).write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        Path(result.snapshot_path).write_text(
            json.dumps(snapshot_payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        Path(result.report_path).write_text(self._render_markdown(result), encoding="utf-8")

    def _write_selection_output(
        self,
        selected_candidates: list[CompanyCandidate],
    ) -> None:
        self.config.selection_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.selection_path.write_text(
            json.dumps(
                {
                    "job_role": self.config.job_role,
                    "top_x": self.config.top_x,
                    "selected_companies": [self._compact_candidate(candidate) for candidate in selected_candidates],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _compact_candidate(candidate: CompanyCandidate) -> dict[str, str | int]:
        return {
            "rank": candidate.rank,
            "name": candidate.name,
            "recruitment_url": candidate.recruitment_url,
        }

    @staticmethod
    def _compact_page(page: CrawledPage) -> dict[str, Any]:
        return {
            "company": page.company,
            "page_url": page.page_url,
            "date": page.date_candidates[:1],
            "site_type": page.site_type,
            "channel_status": page.channel_status,
            "error": page.error,
        }

    def _render_markdown(self, result: WorkflowResult) -> str:
        lines = [
            "# Job Watch Report",
            "",
            f"- 岗位：{result.job_role}",
            f"- 公司数：{result.top_x}",
            f"- 最新公司：{result.analysis.latest_company or '未识别'}",
            f"- 最新日期：{result.analysis.latest_posted_at or '未识别'}",
            f"- 通道状态：{self._status_display(result.analysis.channel_status)}",
            f"- 置信度：{result.analysis.confidence}",
            "",
            "## 公司",
        ]
        for candidate in result.selected_companies:
            lines.append(f"- {candidate.rank}. {candidate.name} | {candidate.recruitment_url}")

        lines.extend(["", "## 页面"])
        for page in result.crawled_pages:
            lines.append(f"- {page.company} | {page.page_url} | {page.site_type} | {self._status_display(page.channel_status)}")
            if page.date_candidates:
                lines.append(f"  - 日期：{', '.join(page.date_candidates[:3])}")
            if page.error:
                lines.append(f"  - 错误：{page.error}")

        lines.extend(["", "## 变化"])
        if result.changes.get("has_previous"):
            lines.append(f"- 有历史快照：是")
            lines.append(f"- 最近日期是否变化：{ '是' if result.changes.get('latest_changed') else '否' }")
            lines.append(f"- 通道状态是否变化：{ '是' if result.changes.get('status_changed') else '否' }")
            for item in result.changes.get("updated_companies", []):
                lines.append(
                    f"- {item.get('company', '')} | {self._status_display(str(item.get('previous_status', 'unknown')))} -> {self._status_display(str(item.get('current_status', 'unknown')))}"
                )
        else:
            lines.append("- 无历史快照")

        lines.extend(["", "## 结果", result.summary])
        return "\n".join(lines) + "\n"

    @staticmethod
    def _status_display(value: str) -> str:
        mapping = {
            "open": "开启",
            "closed": "未开启",
            "unknown": "未知",
        }
        return mapping.get(value.strip().lower(), value or "未知")
