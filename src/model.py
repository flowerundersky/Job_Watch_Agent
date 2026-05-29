"""Network model backend helpers for the job-watch workflow."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import requests

from .config import ModelBackendSettings


class ModelBackend(Protocol):
    def chat(self, messages: Sequence[dict[str, str]]) -> str:
        """Return the model response for the provided chat messages."""


@dataclass(slots=True)
class OpenAICompatibleBackend:
    settings: ModelBackendSettings

    def chat(self, messages: Sequence[dict[str, str]]) -> str:
        if not self.settings.api_base_url.strip():
            raise ValueError("OpenAI-compatible backend requires api_base_url")
        if not self.settings.api_key.strip():
            raise ValueError("OpenAI-compatible backend requires api_key")

        endpoint = _normalize_openai_endpoint(self.settings.api_base_url)
        payload = {
            "model": self.settings.model,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "messages": list(messages),
        }
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            timeout=self.settings.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("unexpected model response structure") from exc


def create_backend(settings: ModelBackendSettings) -> ModelBackend:
    backend_name = settings.backend.strip().lower()
    if backend_name in {"openai", "openai_compatible", "openai-compatible", "api", "proxy", "relay"}:
        return OpenAICompatibleBackend(settings)
    raise ValueError(f"unsupported model backend: {settings.backend!r}; only network model backends are supported")


def _normalize_openai_endpoint(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    if "/v1/" in normalized:
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"
