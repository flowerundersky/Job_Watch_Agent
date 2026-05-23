from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class RuntimeSettings:
    output_dir: Path = Path("output")
    data_dir: Path = Path("data")
    logs_dir: Path = Path("logs")
    timeout_seconds: int = 10


@dataclass(slots=True)
class StopAfterSettings:
    max_matches: int = 10


@dataclass(slots=True)
class ModelBackendSettings:
    backend: str = "rule"
    api_base_url: str = ""
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout_seconds: int = 30
    temperature: float = 0.2
    max_tokens: int = 512
    system_prompt: str = (
        "你是招聘信息分析助手。请根据给定岗位信息判断是否匹配目标条件，"
        "并只返回 JSON，格式为 {\"matched\": true/false, \"score\": number, \"reasons\": [\"...\"]}。"
    )


@dataclass(slots=True)
class AppConfig:
    sources: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    stop_after: StopAfterSettings = field(default_factory=StopAfterSettings)
    model_backend: ModelBackendSettings = field(default_factory=ModelBackendSettings)

    @property
    def snapshot_path(self) -> Path:
        return self.runtime.data_dir / "history.json"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def _to_runtime_settings(data: dict[str, Any] | None) -> RuntimeSettings:
    data = data or {}
    return RuntimeSettings(
        output_dir=Path(data.get("output_dir", "output")),
        data_dir=Path(data.get("data_dir", "data")),
        logs_dir=Path(data.get("logs_dir", "logs")),
        timeout_seconds=int(data.get("timeout_seconds", 10)),
    )


def _to_stop_after_settings(data: dict[str, Any] | None) -> StopAfterSettings:
    data = data or {}
    return StopAfterSettings(max_matches=int(data.get("max_matches", 10)))


def _to_model_backend_settings(data: dict[str, Any] | None) -> ModelBackendSettings:
    data = data or {}
    return ModelBackendSettings(
        backend=str(data.get("backend", "rule")),
        api_base_url=str(data.get("api_base_url", "")),
        api_key=str(data.get("api_key", "")),
        model=str(data.get("model", "gpt-4o-mini")),
        timeout_seconds=int(data.get("timeout_seconds", 30)),
        temperature=float(data.get("temperature", 0.2)),
        max_tokens=int(data.get("max_tokens", 512)),
        system_prompt=str(data.get("system_prompt", ModelBackendSettings.system_prompt)),
    )


def load_config(path: Path) -> AppConfig:
    raw = _read_yaml(path)
    return AppConfig(
        sources=list(raw.get("sources", [])),
        keywords=list(raw.get("keywords", [])),
        companies=list(raw.get("companies", [])),
        runtime=_to_runtime_settings(raw.get("runtime")),
        stop_after=_to_stop_after_settings(raw.get("stop_after")),
        model_backend=_to_model_backend_settings(raw.get("model_backend")),
    )
