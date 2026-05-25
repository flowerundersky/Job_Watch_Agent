from __future__ import annotations

import json
from pathlib import Path

from src.config import AppConfig, ModelBackendSettings, RuntimeSettings
from src.models import CrawledPage
from src.workflow import JobWatchWorkflow


class _DummyBackend:
    def chat(self, messages):
        return json.dumps(
            {
                "job_role": "前端工程师",
                "top_x": 1,
                "companies": [
                    {
                        "rank": 1,
                        "name": "示例公司",
                        "recruitment_url": "https://example.com/careers",
                    }
                ],
            },
            ensure_ascii=False,
        )


def test_langgraph_workflow_runs_end_to_end(tmp_path, monkeypatch) -> None:
    config = AppConfig(
        job_role="前端工程师",
        top_x=1,
        runtime=RuntimeSettings(output_dir=tmp_path),
        model_backend=ModelBackendSettings(backend="heuristic"),
    )
    workflow = JobWatchWorkflow(config)
    workflow.backend = _DummyBackend()

    monkeypatch.setattr(
        "src.workflow.crawl_company_pages",
        lambda candidates, **kwargs: [
            CrawledPage(
                company=candidates[0].name,
                recruitment_url=candidates[0].recruitment_url,
                page_url=candidates[0].recruitment_url,
                site_type="html",
                channel_status="open",
                title="示例招聘页",
                text="2026-05-25 校招进行中",
                date_candidates=["2026-05-25"],
                links=[],
            )
        ],
    )

    result = workflow.run()

    assert result.analysis.latest_company == "示例公司"
    assert result.analysis.latest_posted_at == "2026-05-25"
    assert result.analysis.channel_status == "open"
    assert result.changes["has_previous"] is False
    assert Path(result.result_path).exists()
    assert Path(result.snapshot_path).exists()
    assert Path(result.report_path).exists()