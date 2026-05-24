from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.config import ModelBackendSettings, load_config
from src.workflow import JobWatchWorkflow


@pytest.mark.integration
def test_relay_api_can_select_companies() -> None:
    config_path = Path("config.yaml")
    config = load_config(config_path)

    api_base_url = os.getenv("JOB_WATCH_API_BASE_URL", config.model_backend.api_base_url).strip()
    api_key = os.getenv("JOB_WATCH_API_KEY", config.model_backend.api_key).strip()
    model = os.getenv("JOB_WATCH_MODEL", config.model_backend.model).strip() or config.model_backend.model

    if not api_base_url or not api_key:
        pytest.skip("Set JOB_WATCH_API_BASE_URL and JOB_WATCH_API_KEY (or config.yaml values) to run this test")

    if "example.com" in api_base_url or api_key == "replace-with-your-api-key":
        pytest.skip("Replace placeholder relay settings before running this test")

    config.model_backend = ModelBackendSettings(
        backend="openai_compatible",
        api_base_url=api_base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=config.model_backend.timeout_seconds,
        temperature=config.model_backend.temperature,
        max_tokens=config.model_backend.max_tokens,
        system_prompt=config.model_backend.system_prompt,
    )

    workflow = JobWatchWorkflow(config)
    candidates, raw_output = workflow._select_companies()

    output_path = Path("output/test_output/test_relay_connect.json")
    output_payload = {
        "job_role": config.job_role,
        "top_x": config.top_x,
        "model_backend": {
            "backend": config.model_backend.backend,
            "api_base_url": api_base_url,
            "model": model,
        },
        "raw_output": raw_output,
        "candidates": [candidate.to_dict() for candidate in candidates],
    }
    output_path.write_text(json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    assert raw_output.strip(), "model backend returned empty output"
    assert candidates, f"expected at least one company candidate, got raw output: {raw_output}"
    assert candidates[0].name.strip()
    assert candidates[0].recruitment_url.strip()
    assert candidates[0].rank >= 1
