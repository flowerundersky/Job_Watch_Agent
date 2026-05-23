from pathlib import Path

from src.config import load_config


def test_load_config_uses_defaults_when_file_is_missing(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing.yaml")

    assert config.sources == []
    assert config.keywords == []
    assert config.companies == []
    assert config.runtime.output_dir == Path("output")
    assert config.snapshot_path == Path("data") / "history.json"
    assert config.model_backend.backend == "rule"


def test_load_config_reads_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
sources:
  - https://example.com/careers
keywords:
  - Python
companies:
  - 示例科技
runtime:
  output_dir: reports
  data_dir: snapshots
  logs_dir: logs
  timeout_seconds: 15
stop_after:
  max_matches: 8
model_backend:
  backend: openai_compatible
  api_base_url: https://proxy.example.com/v1
  api_key: test-token
  model: qwen-plus
  timeout_seconds: 20
  temperature: 0.1
  max_tokens: 256
""",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.sources == ["https://example.com/careers"]
    assert config.keywords == ["Python"]
    assert config.companies == ["示例科技"]
    assert config.runtime.output_dir == Path("reports")
    assert config.runtime.data_dir == Path("snapshots")
    assert config.runtime.timeout_seconds == 15
    assert config.stop_after.max_matches == 8
    assert config.model_backend.backend == "openai_compatible"
    assert config.model_backend.api_base_url == "https://proxy.example.com/v1"
    assert config.model_backend.api_key == "test-token"
    assert config.model_backend.model == "qwen-plus"
