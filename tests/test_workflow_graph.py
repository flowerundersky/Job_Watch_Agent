from __future__ import annotations

import json
from pathlib import Path

from src.config import AppConfig, ModelBackendSettings, RuntimeSettings
from src.models import CrawledPage
from src.workflow import JobWatchWorkflow


class _DummyBackend:
    def __init__(self) -> None:
        self.messages = []
        self.calls = []

    def chat(self, messages):
        current_messages = list(messages)
        self.messages = current_messages
        self.calls.append(current_messages)
        system_text = " ".join(str(message.get("content", "")) for message in current_messages if message.get("role") == "system")
        if "channel_status" in system_text:
            return json.dumps(
                {
                    "job_role": "前端工程师",
                    "is_sufficient": True,
                    "reason": "示例页面信息已经足够",
                    "next_hops": [],
                    "channel_status": "open",
                    "confidence": "high",
                },
                ensure_ascii=False,
            )
        if "latest_posted_at" in system_text:
            return json.dumps(
                {
                    "job_role": "前端工程师",
                    "is_sufficient": True,
                    "reason": "示例页面信息已经足够",
                    "next_hops": [],
                    "latest_company": "示例公司",
                    "latest_posted_at": "2026-05-25",
                    "confidence": "high",
                },
                ensure_ascii=False,
            )
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
        company_filters="优先校招官网；只看技术岗",
        top_x=1,
        runtime=RuntimeSettings(output_dir=tmp_path),
        model_backend=ModelBackendSettings(backend="heuristic"),
    )
    workflow = JobWatchWorkflow(config)
    backend = _DummyBackend()
    workflow.backend = backend

    monkeypatch.setattr(
        "src.workflow.crawl_url",
        lambda company, recruitment_url, **kwargs: CrawledPage(
            company=company,
            recruitment_url=recruitment_url,
            page_url=recruitment_url,
            task_type="date",
            site_type="html",
            channel_status="open",
            latest_posted_at="2026-05-25",
            decision_confidence="high",
            is_sufficient=True,
            title="示例招聘页",
            text="2026-05-25 校招进行中",
            date_candidates=["2026-05-25"],
            links=[],
            next_hops=[],
            visited_urls=[recruitment_url],
            decision_reason="示例页面信息已经足够",
        ),
    )

    result = workflow.run()

    assert any(
        "筛选条件：优先校招官网；只看技术岗" in str(message.get("content", ""))
        for call in backend.calls
        for message in call
    )
    assert result.analysis.latest_company == "示例公司"
    assert result.analysis.latest_posted_at == "2026-05-25"
    assert result.analysis.channel_status == "open"
    assert result.changes["has_previous"] is False
    assert Path(result.result_path).exists()
    assert Path(result.snapshot_path).exists()
    assert Path(result.report_path).exists()