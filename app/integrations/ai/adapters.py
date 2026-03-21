from __future__ import annotations

from typing import Any

import httpx

from app.core.exceptions import AIProviderError
from app.integrations.ai.base import AIAdapter, extract_json_object


class OllamaAdapter(AIAdapter):
    def __init__(self, *, base_url: str, model: str, timeout: float) -> None:
        self.provider = "ollama"
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": False,
            "format": "json",
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{self.base_url}/api/generate", json=payload)
            response.raise_for_status()
            body = response.json()
        content = body.get("response")
        if not isinstance(content, str):
            raise AIProviderError("Ollama returned an unexpected response body.")
        return extract_json_object(content)


class RemoteAIAdapter(AIAdapter):
    def __init__(self, *, base_url: str, model: str, api_key: str, timeout: float) -> None:
        self.provider = "remote"
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
        choices = body.get("choices") or []
        if not choices:
            raise AIProviderError("Remote AI provider returned no completion choices.")
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str):
            raise AIProviderError("Remote AI provider returned an unexpected completion payload.")
        return extract_json_object(content)


class StubAIAdapter(AIAdapter):
    def __init__(self) -> None:
        self.provider = "stub"
        self.model = "deterministic"

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return {"system_prompt": system_prompt, "user_prompt": user_prompt}
