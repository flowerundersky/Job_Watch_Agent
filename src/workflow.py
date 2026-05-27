"""Second-version job-watch workflow orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .config import AppConfig
from .crawler import crawl_company_page, crawl_url
from .model import OpenAICompatibleBackend, create_backend
from .models import AnalysisResult, CompanyCandidate, CrawledPage, WorkflowResult
from .prompt import (
    build_channel_status_messages,
    build_company_selection_messages,
    build_company_selection_retry_message,
    build_latest_date_messages,
    extract_json_object,
)


class WorkflowState(TypedDict, total=False):
    selected_candidates: list[CompanyCandidate]
    missing_candidates: list[dict[str, Any]]
    date_crawled_pages: list[CrawledPage]
    channel_crawled_pages: list[CrawledPage]
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
        selection = self._select_companies_with_missing()
        self._write_selection_output(selection["selected"], selection["missing"])
        print("公司筛选已完成")
        return {
            "selected_candidates": selection["selected"],
            "missing_candidates": selection["missing"],
        }

    def _graph_crawl_pages(self, state: WorkflowState) -> dict[str, Any]:
        selected_candidates = state["selected_candidates"]
        print("开始抓取页面")
        with ThreadPoolExecutor(max_workers=2) as executor:
            date_future = executor.submit(self._crawl_time_pages, selected_candidates)
            channel_future = executor.submit(self._crawl_channel_pages, selected_candidates)
            date_pages = date_future.result()
            channel_pages = channel_future.result()
        return {
            "date_crawled_pages": date_pages,
            "channel_crawled_pages": channel_pages,
        }

    def _graph_analyze(self, state: WorkflowState) -> dict[str, Any]:
        date_pages = state.get("date_crawled_pages", [])
        channel_pages = state.get("channel_crawled_pages", [])
        analysis = self._combine_agent_results(date_pages, channel_pages)
        return {"analysis": analysis}

    def _graph_persist(self, state: WorkflowState) -> dict[str, Any]:
        selected_candidates = state["selected_candidates"]
        missing_candidates = state.get("missing_candidates", [])
        date_pages = state.get("date_crawled_pages", [])
        channel_pages = state.get("channel_crawled_pages", [])
        crawled_pages = [*date_pages, *channel_pages]
        analysis = state["analysis"]
        changes = self._build_changes(crawled_pages, analysis)
        result = WorkflowResult(
            job_role=self.config.job_role,
            top_x=self.config.top_x,
            selected_companies=selected_candidates,
            missing_companies=missing_candidates,
            crawled_pages=crawled_pages,
            analysis=analysis,
            report_path=str(self.config.report_path),
            result_path=str(self.config.result_path),
            snapshot_path=str(self.config.snapshot_path),
            summary=self._build_summary(selected_candidates, crawled_pages, analysis),
            changes=changes,
        )

        self._write_outputs(result)
        print("结果已生成")
        return {"result": result, "changes": changes}

    def _select_companies(self) -> list[CompanyCandidate]:
        return self._select_companies_with_missing()["selected"]

    def _select_companies_with_missing(self) -> dict[str, Any]:
        messages = build_company_selection_messages(
            self.config.job_role,
            self.config.top_x,
            self.config.company_filters,
        )
        raw_output = self.backend.chat(messages)
        payload = extract_json_object(raw_output)
        candidates, missing_candidates = self._parse_company_candidates(payload)

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
            new_candidates, rejected_items = self._parse_company_candidates(payload)
            candidates = self._merge_company_candidates(candidates, new_candidates)
            missing_candidates = self._merge_missing_candidates(missing_candidates, rejected_items)

        selected = candidates[: self.config.top_x]
        missing = self._finalize_missing_candidates(selected, missing_candidates)
        return {"selected": selected, "missing": missing}

    def _combine_agent_results(self, date_pages: list[CrawledPage], channel_pages: list[CrawledPage]) -> AnalysisResult:
        latest_company = ""
        latest_posted_at = ""
        latest_confidence = "low"
        for page in date_pages:
            if page.latest_posted_at and not latest_posted_at:
                latest_company = page.company
                latest_posted_at = page.latest_posted_at
                latest_confidence = page.decision_confidence or "low"
        if not latest_company and date_pages:
            latest_company = date_pages[0].company

        channel_status = "unknown"
        channel_confidence = "low"
        for page in channel_pages:
            if page.channel_status in {"open", "closed"}:
                channel_status = page.channel_status
                channel_confidence = page.decision_confidence or "high"
                break

        confidence = latest_confidence if latest_confidence != "low" else channel_confidence
        return AnalysisResult(
            job_role=self.config.job_role,
            latest_company=latest_company,
            latest_posted_at=latest_posted_at,
            channel_status=channel_status,
            confidence=confidence,
        )

    def _crawl_time_pages(self, candidates: list[CompanyCandidate]) -> list[CrawledPage]:
        return [self._crawl_time_agent(candidate) for candidate in candidates]

    def _crawl_channel_pages(self, candidates: list[CompanyCandidate]) -> list[CrawledPage]:
        return [self._crawl_channel_agent(candidate) for candidate in candidates]

    def _crawl_time_agent(self, candidate: CompanyCandidate) -> CrawledPage:
        visited_urls: list[str] = []
        current_url = candidate.recruitment_url
        final_page: CrawledPage | None = None

        for _ in range(3):
            page = crawl_url(
                candidate.name,
                current_url,
                timeout_seconds=self.config.runtime.timeout_seconds,
                max_crawl_chars=self.config.runtime.max_crawl_chars,
                max_links_per_page=self.config.runtime.max_links_per_page,
            )
            print(f"公司 {candidate.name} 时间 agent 已爬取页面: {page.page_url}")
            visited_urls.append(page.page_url)
            decision = extract_json_object(
                self.backend.chat(
                    build_latest_date_messages(
                        self.config.job_role,
                        candidate.name,
                        page.page_url,
                        page.observation,
                    )
                )
            )
            page.is_sufficient = bool(decision.get("is_sufficient"))
            page.decision_reason = str(decision.get("reason", "")).strip()
            page.next_hops = self._normalize_next_hops(page.links, decision.get("next_hops", []), page.page_url)
            page.visited_urls = list(visited_urls)
            page.task_type = "date"
            page.latest_posted_at = str(decision.get("latest_posted_at", "")).strip()
            page.decision_confidence = str(decision.get("confidence", "low")).strip() or "low"
            page.date_candidates = [page.latest_posted_at] if page.latest_posted_at else list(page.date_candidates)
            final_page = page
            if page.is_sufficient or not page.next_hops:
                break
            current_url = page.next_hops[0]

        latest_posted_at = final_page.latest_posted_at if final_page else ""
        print(f"公司 {candidate.name} 时间 agent 已完成，最新发布日期: {latest_posted_at or '未找到'}")
        return final_page or crawl_company_page(candidate)

    def _crawl_channel_agent(self, candidate: CompanyCandidate) -> CrawledPage:
        visited_urls: list[str] = []
        current_url = candidate.recruitment_url
        final_page: CrawledPage | None = None

        for _ in range(3):
            page = crawl_url(
                candidate.name,
                current_url,
                timeout_seconds=self.config.runtime.timeout_seconds,
                max_crawl_chars=self.config.runtime.max_crawl_chars,
                max_links_per_page=self.config.runtime.max_links_per_page,
            )
            print(f"公司 {candidate.name} 通道 agent 已爬取页面: {page.page_url}")
            visited_urls.append(page.page_url)
            decision = extract_json_object(
                self.backend.chat(
                    build_channel_status_messages(
                        self.config.job_role,
                        candidate.name,
                        page.page_url,
                        page.observation,
                    )
                )
            )
            page.is_sufficient = bool(decision.get("is_sufficient"))
            page.decision_reason = str(decision.get("reason", "")).strip()
            page.next_hops = self._normalize_next_hops(page.links, decision.get("next_hops", []), page.page_url)
            page.visited_urls = list(visited_urls)
            page.task_type = "channel"
            page.channel_status = str(decision.get("channel_status", page.channel_status or "unknown")).strip() or "unknown"
            page.decision_confidence = str(decision.get("confidence", "low")).strip() or "low"
            final_page = page
            if page.is_sufficient or not page.next_hops:
                break
            current_url = page.next_hops[0]

        channel_status = final_page.channel_status if final_page else "unknown"
        print(f"公司 {candidate.name} 通道 agent 已完成，通道状态: {channel_status}")
        return final_page or crawl_company_page(candidate)

    @staticmethod
    def _normalize_next_hops(available_links: list[str], recommended_links: Any, page_url: str) -> list[str]:
        available = {link.strip() for link in available_links if isinstance(link, str) and link.strip()}
        normalized: list[str] = []
        if not isinstance(recommended_links, list):
            return normalized
        for item in recommended_links:
            link = str(item).strip()
            if not link or link == page_url:
                continue
            if link in available and link not in normalized:
                normalized.append(link)
        return normalized[:3]

    def _parse_company_candidates(self, payload: dict[str, Any]) -> tuple[list[CompanyCandidate], list[dict[str, Any]]]:
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
                item.get("recruitment_url")
                or item.get("url")
                or item.get("career_url")
                or item.get("careers_url")
                or ""
            ).strip()
            if not name or not recruitment_url:
                missing.append(
                    {
                        "rank": int(item.get("rank") or index),
                        "name": name,
                        "recruitment_url": recruitment_url,
                        "reason": str(item.get("reason") or "").strip(),
                        "missing_reason": "missing name or recruitment_url",
                    }
                )
                continue
            if not self._looks_like_campus_recruitment_url(recruitment_url):
                missing.append(
                    {
                        "rank": int(item.get("rank") or index),
                        "name": name,
                        "recruitment_url": recruitment_url,
                        "reason": str(item.get("reason") or "").strip(),
                        "missing_reason": "url not campus-like",
                    }
                )
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
        return candidates, missing

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

    def _merge_missing_candidates(
        self,
        existing: list[dict[str, Any]],
        new_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = list(existing)
        seen_keys = {
            (
                str(item.get("name") or "").strip().lower(),
                str(item.get("recruitment_url") or "").strip().lower(),
                str(item.get("missing_reason") or "").strip().lower(),
            )
            for item in merged
        }
        for item in new_items:
            key = (
                str(item.get("name") or "").strip().lower(),
                str(item.get("recruitment_url") or "").strip().lower(),
                str(item.get("missing_reason") or "").strip().lower(),
            )
            if key in seen_keys:
                continue
            merged.append(item)
            seen_keys.add(key)
        return merged

    def _finalize_missing_candidates(
        self,
        selected_candidates: list[CompanyCandidate],
        missing_candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        missing = list(missing_candidates)
        remaining = max(0, self.config.top_x - len(selected_candidates))
        for index in range(remaining):
            missing.append(
                {
                    "rank": len(selected_candidates) + index + 1,
                    "missing_reason": "not filled after retries",
                }
            )
        return missing

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
        selected_companies = [self._compact_candidate(candidate) for candidate in result.selected_companies]
        crawled_pages = [self._compact_page(page) for page in result.crawled_pages]
        analysis_payload = {
            "job_role": result.analysis.job_role,
            "latest_company": result.analysis.latest_company,
            "latest_posted_at": result.analysis.latest_posted_at,
            "channel_status": result.analysis.channel_status,
            "confidence": result.analysis.confidence,
        }
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
        }
        snapshot_payload = {
            "metadata": metadata_payload,
            "selection": selection_payload,
            "crawl": crawl_payload,
            "analysis": analysis_payload,
            "changes": result.changes,
            "structure_note": "selection=公司筛选结果; crawl=爬取页面结果; analysis=最终判断",
            # Backward-compatible top-level fields.
            "job_role": result.job_role,
            "top_x": result.top_x,
            "selected_companies": selected_companies,
            "missing_companies": result.missing_companies,
            "crawled_pages": crawled_pages,
        }
        payload = self._build_result_payload(result.selected_companies, result.crawled_pages)
        Path(result.result_path).parent.mkdir(parents=True, exist_ok=True)
        Path(result.snapshot_path).parent.mkdir(parents=True, exist_ok=True)
        Path(result.report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(result.result_path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        Path(result.snapshot_path).write_text(
            json.dumps(snapshot_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        Path(result.report_path).write_text(self._render_markdown(result), encoding="utf-8")

    def _build_result_payload(
        self,
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
                    "latest_posted_at": "",
                    "channel_status": "unknown",
                },
            )
            if page.page_url and not record["website"]:
                record["website"] = page.page_url
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
                    "latest_posted_at": record.get("latest_posted_at", ""),
                    "channel_status": record.get("channel_status", "unknown"),
                }
            )

        return {
            "companies": companies,
        }

    def _write_selection_output(
        self,
        selected_candidates: list[CompanyCandidate],
        missing_candidates: list[dict[str, Any]],
    ) -> None:
        self.config.selection_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.selection_path.write_text(
            json.dumps(
                {
                    "selection": {
                        "selected_companies": [self._compact_candidate(candidate) for candidate in selected_candidates],
                    },
                    "missing": missing_candidates,
                },
                ensure_ascii=False,
                indent=2,
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

    @staticmethod
    def _looks_like_campus_recruitment_url(url: str) -> bool:
        from urllib.parse import unquote, urlparse

        normalized = unquote(url).lower()
        parsed = urlparse(normalized)
        target = f"{parsed.netloc}{parsed.path}"
        hints = (
            "career",
            "careers",
            "job",
            "jobs",
            "talent",
            "recruit",
            "recruitment",
            "zhaopin",
            "campus",
            "campus-recruit",
            "school-recruit",
            "graduate",
            "campus招聘",
            "校招",
            "招聘",
        )
        return any(hint in target for hint in hints)
