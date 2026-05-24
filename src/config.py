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
    report_filename: str = "job_watch_report.md"
    result_filename: str = "job_watch_result.json"


@dataclass(slots=True)
class ModelBackendSettings:
    backend: str = "openai_compatible"
    api_base_url: str = ""
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout_seconds: int = 30
    temperature: float = 0.0
    max_tokens: int = 1024
    system_prompt: str = (
        "你是招聘情报分析助手。你需要根据岗位名称筛选最可能发布此岗位招聘信息的公司，"
        "并在第二阶段判断这些公司招聘页面上最近一次招聘信息是什么时候发布的。"
        "只返回 JSON，不要输出解释。"
    )


@dataclass(slots=True)
class AppConfig:
    job_role: str = "前端工程师"
    top_x: int = 3
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    model_backend: ModelBackendSettings = field(default_factory=ModelBackendSettings)

    @property
    def snapshot_path(self) -> Path:
        return self.runtime.output_dir / "job_watch_snapshot.json"

    @property
    def report_path(self) -> Path:
        return self.runtime.output_dir / self.runtime.report_filename

    @property
    def result_path(self) -> Path:
        return self.runtime.output_dir / self.runtime.result_filename


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
        report_filename=str(data.get("report_filename", "job_watch_report.md")),
        result_filename=str(data.get("result_filename", "job_watch_result.json")),
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
        system_prompt=str(data.get("system_prompt", ModelBackendSettings.system_prompt)),
    )


def load_config(path: Path) -> AppConfig:
    raw = _read_yaml(path)
    return AppConfig(
        job_role=str(raw.get("job_role", "前端工程师")),
        top_x=int(raw.get("top_x", 3)),
        runtime=_to_runtime_settings(raw.get("runtime")),
        model_backend=_to_model_backend_settings(raw.get("model_backend")),
    )
