"""JSON parsing helpers."""

from __future__ import annotations

import json
from typing import Any


def extract_json_object(raw_text: str) -> dict[str, Any]:
    """Extract a JSON object from a model response."""

    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("model response does not contain a JSON object")

    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("model response JSON is not an object")
    return payload
