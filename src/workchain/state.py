"""Shared workflow state and runtime context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

from ..config import AppConfig
from ..models import AnalysisResult, CompanyCandidate, CrawledPage, WorkflowResult


class ChatBackend(Protocol):
    def chat(self, messages: list[dict[str, str]]) -> str:
        """Return the model response for the provided chat messages."""


@dataclass(slots=True)
class WorkflowContext:
    config: AppConfig
    backend: ChatBackend


class WorkflowState(TypedDict, total=False):
    selected_candidates: list[CompanyCandidate]
    missing_candidates: list[dict[str, Any]]
    date_crawled_pages: list[CrawledPage]
    channel_crawled_pages: list[CrawledPage]
    analysis: AnalysisResult
    changes: dict[str, Any]
    result: WorkflowResult
