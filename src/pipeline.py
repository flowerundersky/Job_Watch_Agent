from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.analyzer import AnalyzerSettings, LLMAnalyzer
from src.cleaner import deduplicate_jobs
from src.comparator import compare_job_snapshots
from src.config import AppConfig
from src.models import RunResult
from src.reporter import generate_pdf_report
from src.scraper import JobScraper
from src.storage import load_snapshot, save_snapshot


@dataclass(slots=True)
class PipelineOutput:
    report_path: Path
    snapshot_path: Path
    summary: str


class JobMonitorPipeline:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.scraper = JobScraper(timeout_seconds=config.runtime.timeout_seconds)
        self.analyzer = LLMAnalyzer(
            AnalyzerSettings(
                keywords=list(config.keywords),
                companies=list(config.companies),
                min_score=1.0,
            ),
            backend=config.model_backend,
        )

    def _ensure_directories(self) -> None:
        self.config.runtime.output_dir.mkdir(parents=True, exist_ok=True)
        self.config.runtime.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.runtime.logs_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> RunResult:
        self._ensure_directories()

        previous_jobs = load_snapshot(self.config.snapshot_path)
        current_jobs = deduplicate_jobs(self.scraper.scrape_urls(self.config.sources))
        delta = compare_job_snapshots(previous_jobs, current_jobs)

        candidates = delta.new_jobs + delta.changed_jobs
        if not candidates:
            candidates = list(current_jobs)

        match_results = self.analyzer.analyze(candidates)
        matched_results = [result for result in match_results if result.matched]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.config.runtime.output_dir / f"job_monitor_report_{timestamp}.pdf"
        generate_pdf_report(
            report_path,
            title="招聘监控报告",
            summary_lines=[
                f"sources: {len(self.config.sources)}",
                f"total jobs: {len(current_jobs)}",
                f"new jobs: {len(delta.new_jobs)}",
                f"changed jobs: {len(delta.changed_jobs)}",
                f"removed jobs: {len(delta.removed_jobs)}",
                f"matched jobs: {len(matched_results)}",
            ],
            matched_jobs=matched_results,
            changed_jobs=delta.changed_jobs,
        )

        save_snapshot(self.config.snapshot_path, current_jobs)

        summary = (
            f"run complete: total={len(current_jobs)}, new={len(delta.new_jobs)}, "
            f"changed={len(delta.changed_jobs)}, removed={len(delta.removed_jobs)}, matched={len(matched_results)}"
        )
        return RunResult(
            total_jobs=len(current_jobs),
            new_jobs=len(delta.new_jobs),
            changed_jobs=len(delta.changed_jobs),
            removed_jobs=len(delta.removed_jobs),
            matched_jobs=len(matched_results),
            report_path=str(report_path),
            snapshot_path=str(self.config.snapshot_path),
            summary=summary,
        )
