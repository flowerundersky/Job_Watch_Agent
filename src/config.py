from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class RuntimeSettings:
    output_dir: Path = Path("output")
    timeout_seconds: int = 15
    max_crawl_chars: int = 12000
    max_links_per_page: int = 20
    report_filename: str = "result_output/job_watch_report.md"
    result_filename: str = "result_output/job_watch_result.json"
    snapshot_filename: str = "result_output/job_watch_snapshot.json"
    selection_filename: str = "result_output/job_watch_selection.json"


@dataclass(slots=True)
class ModelBackendSettings:
    backend: str = "openai_compatible"
    api_base_url: str = ""
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout_seconds: int = 30
    temperature: float = 0.0
    max_tokens: int = 1024


@dataclass(slots=True)
class AppConfig:
    job_role: str = "前端工程师"
    company_filters: str = ""
    top_x: int = 3
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    model_backend: ModelBackendSettings = field(default_factory=ModelBackendSettings)

    @property
    def snapshot_path(self) -> Path:
        return self.runtime.output_dir / self.runtime.snapshot_filename

    @property
    def report_path(self) -> Path:
        return self.runtime.output_dir / self.runtime.report_filename

    @property
    def result_path(self) -> Path:
        return self.runtime.output_dir / self.runtime.result_filename

    @property
    def selection_path(self) -> Path:
        return self.runtime.output_dir / self.runtime.selection_filename


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def _to_runtime_settings(data: dict[str, Any] | None) -> RuntimeSettings:
    data = data or {}
    return RuntimeSettings(
        output_dir=Path(data.get("output_dir", "output")),
        timeout_seconds=int(data.get("timeout_seconds", 15)),
        max_crawl_chars=int(data.get("max_crawl_chars", 12000)),
        max_links_per_page=int(data.get("max_links_per_page", 20)),
        report_filename=str(data.get("report_filename", "result_output/job_watch_report.md")),
        result_filename=str(data.get("result_filename", "result_output/job_watch_result.json")),
        snapshot_filename=str(data.get("snapshot_filename", "result_output/job_watch_snapshot.json")),
        selection_filename=str(data.get("selection_filename", "result_output/job_watch_selection.json")),
    )


def _to_model_backend_settings(data: dict[str, Any] | None) -> ModelBackendSettings:
    data = data or {}
    return ModelBackendSettings(
        backend=str(data.get("backend", "openai_compatible")),
        api_base_url=str(data.get("api_base_url", "")),
        api_key=str(data.get("api_key", "")),
        model=str(data.get("model", "gpt-4o-mini")),
        timeout_seconds=int(data.get("timeout_seconds", 30)),
        temperature=float(data.get("temperature", 0.0)),
        max_tokens=int(data.get("max_tokens", 1024)),
    )


def load_config(path: Path) -> AppConfig:
    raw = _read_yaml(path)
    return AppConfig(
        job_role=str(raw.get("job_role", "前端工程师")),
        company_filters=str(raw.get("company_filters", "")),
        top_x=int(raw.get("top_x", 3)),
        runtime=_to_runtime_settings(raw.get("runtime")),
        model_backend=_to_model_backend_settings(raw.get("model_backend")),
    )
