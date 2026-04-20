"""Single entry point for every AI call made by Qony's backend.

Per project conventions, no route handler or service may call OpenAI,
Ollama, or any other LLM provider directly. They must obtain an
``AIRouter`` through :func:`get_ai_router` and invoke
:meth:`AIRouter.complete_json`.

The router encapsulates three concrete providers:

* ``stub`` — deterministic, offline; used by tests and local development.
* ``ollama`` — local LLM served via Ollama's HTTP API.
* ``remote`` — OpenAI-compatible ``/chat/completions`` endpoint.

All providers return a parsed JSON object. Prompt construction, retry,
logging, and fallback semantics live in ``ai_service.py``; the router
stays thin.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import AIProviderError
from app.domain.enums import AIProviderKind


class _AIProvider(ABC):
    provider: str
    model: str | None

    @abstractmethod
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        raise NotImplementedError


class _OllamaProvider(_AIProvider):
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
        return _extract_json_object(content)


class _RemoteProvider(_AIProvider):
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
            response = client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
            body = response.json()
        choices = body.get("choices") or []
        if not choices:
            raise AIProviderError("Remote AI provider returned no completion choices.")
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str):
            raise AIProviderError("Remote AI provider returned an unexpected completion payload.")
        return _extract_json_object(content)


class _StubProvider(_AIProvider):
    def __init__(self) -> None:
        self.provider = "stub"
        self.model = "deterministic"

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return {"system_prompt": system_prompt, "user_prompt": user_prompt}


class AIRouter:
    """Dispatches AI calls to the configured provider."""

    def __init__(self, settings: Settings) -> None:
        self._provider = _build_provider(settings)

    @property
    def provider(self) -> str:
        return self._provider.provider

    @property
    def model(self) -> str | None:
        return self._provider.model

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return self._provider.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )


def get_ai_router(settings: Settings) -> AIRouter:
    """Return a fresh router bound to the given settings.

    We deliberately avoid a process-wide cache because tests mutate
    ``Settings`` in place to simulate provider failures. Constructing a
    router is cheap — the underlying providers are plain objects and
    open HTTP clients lazily inside ``complete_json``.
    """

    return AIRouter(settings)


def _build_provider(settings: Settings) -> _AIProvider:
    if settings.ai_provider == AIProviderKind.OLLAMA:
        return _OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=settings.ai_request_timeout_seconds,
        )
    if settings.ai_provider == AIProviderKind.REMOTE:
        return _RemoteProvider(
            base_url=settings.remote_ai_base_url,
            model=settings.remote_ai_model,
            api_key=settings.remote_ai_api_key_value,
            timeout=settings.ai_request_timeout_seconds,
        )
    return _StubProvider()


def _extract_json_object(raw_text: str) -> dict[str, Any]:
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
