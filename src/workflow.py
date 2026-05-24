"""Second-version job-watch workflow orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import AppConfig
from .crawler import crawl_company_pages
from .model import OpenAICompatibleBackend, analyze_latest_posting, create_backend
from .models import AnalysisResult, CompanyCandidate, CrawledPage, WorkflowResult
from .prompt import (
    build_analysis_messages,
    build_company_selection_messages,
    build_company_selection_retry_message,
    extract_json_object,
)


class JobWatchWorkflow:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.backend = create_backend(config.model_backend)

    def run(self) -> WorkflowResult:
        self.config.runtime.output_dir.mkdir(parents=True, exist_ok=True)

        selected_candidates, raw_selection_output = self._select_companies()
        self._write_selection_output(selected_candidates, raw_selection_output)
        crawled_pages = crawl_company_pages(
            selected_candidates,
            timeout_seconds=self.config.runtime.timeout_seconds,
            max_crawl_chars=self.config.runtime.max_crawl_chars,
            max_links_per_page=self.config.runtime.max_links_per_page,
        )
        analysis, raw_analysis_output = self._analyze_latest_posting(selected_candidates, crawled_pages)

        result = WorkflowResult(
            job_role=self.config.job_role,
            top_x=self.config.top_x,
            selected_companies=selected_candidates,
            crawled_pages=crawled_pages,
            analysis=analysis,
            raw_selection_output=raw_selection_output,
            raw_analysis_output=raw_analysis_output,
            report_path=str(self.config.report_path),
            result_path=str(self.config.result_path),
            snapshot_path=str(self.config.snapshot_path),
            summary=self._build_summary(selected_candidates, crawled_pages, analysis),
        )

        self._write_outputs(result)
        return result

    def _select_companies(self) -> tuple[list[CompanyCandidate], str]:
        messages = build_company_selection_messages(self.config.job_role, self.config.top_x)
        raw_output = self.backend.chat(messages)
        payload = extract_json_object(raw_output)
        candidates = self._parse_company_candidates(payload)

        attempts = 0
        while len(candidates) < self.config.top_x and attempts < 2:
            attempts += 1
            current_payload = [candidate.to_dict() for candidate in candidates]
            messages = messages + [
                {"role": "assistant", "content": raw_output},
                *build_company_selection_retry_message(self.config.job_role, self.config.top_x, current_payload),
            ]
            raw_output = self.backend.chat(messages)
            payload = extract_json_object(raw_output)
            candidates = self._merge_company_candidates(candidates, self._parse_company_candidates(payload))

        if len(candidates) < self.config.top_x:
            raise ValueError(
                f"company selection returned only {len(candidates)} candidates, expected {self.config.top_x}"
            )

        return candidates[: self.config.top_x], raw_output

    def _analyze_latest_posting(
        self,
        selected_companies: list[CompanyCandidate],
        crawled_pages: list[CrawledPage],
    ) -> tuple[AnalysisResult, str]:
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
                evidence=str(payload.get("evidence", "")),
                summary=str(payload.get("summary", "")),
                confidence=str(payload.get("confidence", "low")),
                raw_output=raw_output,
            )
            return analysis, raw_output

        analysis = analyze_latest_posting(self.config.job_role, selected_companies, crawled_pages)
        raw_output = json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2)
        analysis.raw_output = raw_output
        return analysis, raw_output

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
            f"crawled={len(crawled_pages)}; latest={analysis.latest_company or '未识别'}; "
            f"posted_at={analysis.latest_posted_at or '未识别'}"
        )

    def _write_outputs(self, result: WorkflowResult) -> None:
        payload = result.to_dict()
        Path(result.result_path).parent.mkdir(parents=True, exist_ok=True)
        Path(result.snapshot_path).parent.mkdir(parents=True, exist_ok=True)
        Path(result.report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(result.result_path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        Path(result.snapshot_path).write_text(
            json.dumps(
                {
                    "job_role": result.job_role,
                    "top_x": result.top_x,
                    "selected_companies": [candidate.to_dict() for candidate in result.selected_companies],
                    "crawled_pages": [page.to_dict() for page in result.crawled_pages],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        Path(result.report_path).write_text(self._render_markdown(result), encoding="utf-8")

    def _write_selection_output(
        self,
        selected_candidates: list[CompanyCandidate],
        raw_selection_output: str,
    ) -> None:
        self.config.selection_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.selection_path.write_text(
            json.dumps(
                {
                    "job_role": self.config.job_role,
                    "top_x": self.config.top_x,
                    "raw_selection_output": raw_selection_output,
                    "selected_companies": [candidate.to_dict() for candidate in selected_candidates],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _render_markdown(self, result: WorkflowResult) -> str:
        lines = [
            "# Job Watch Report",
            "",
            f"- 岗位：{result.job_role}",
            f"- 候选公司数：{result.top_x}",
            f"- 最近一次招聘信息公司：{result.analysis.latest_company or '未识别'}",
            f"- 最近一次招聘信息发布时间：{result.analysis.latest_posted_at or '未识别'}",
            f"- 置信度：{result.analysis.confidence}",
            "",
            "## 第一阶段公司结果",
        ]
        for candidate in result.selected_companies:
            lines.append(
                f"- {candidate.rank}. {candidate.name} | {candidate.recruitment_url} | {candidate.reason}".rstrip()
            )

        lines.extend(["", "## 官网抓取结果"])
        for page in result.crawled_pages:
            lines.append(f"- {page.company} | {page.page_url}")
            if page.title:
                lines.append(f"  - 标题：{page.title}")
            if page.date_candidates:
                lines.append(f"  - 日期线索：{', '.join(page.date_candidates[:5])}")
            if page.error:
                lines.append(f"  - 错误：{page.error}")

        lines.extend(["", "## 第二阶段分析", result.analysis.summary])
        if result.analysis.evidence:
            lines.append(f"证据：{result.analysis.evidence}")
        return "\n".join(lines) + "\n"
