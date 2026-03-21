from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any


class AIAdapter(ABC):
    provider: str
    model: str | None

    @abstractmethod
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        raise NotImplementedError


def extract_json_object(raw_text: str) -> dict[str, Any]:
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if "\n" in stripped:
            stripped = stripped.split("\n", 1)[1]
        if stripped.endswith("```"):
            stripped = stripped[:-3].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("AI response did not contain a JSON object")
    return json.loads(stripped[start : end + 1])
