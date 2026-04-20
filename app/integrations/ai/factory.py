from __future__ import annotations

from typing import Literal

from app.core.config import Settings
from app.integrations.ai.adapters import OllamaAdapter, RemoteAIAdapter, StubAIAdapter
from app.integrations.ai.base import AIAdapter


def build_ai_adapter(
    settings: Settings,
    *,
    use_case: Literal["extraction", "generation", "scraping"] = "generation",
) -> AIAdapter:
    provider = settings.effective_ai_provider
    if provider == "ollama":
        return OllamaAdapter(
            base_url=settings.ollama_base_url,
            model=settings.model_for_use_case(use_case),
            timeout=settings.ai_request_timeout_seconds,
        )
    if provider == "remote":
        return RemoteAIAdapter(
            base_url=settings.remote_ai_base_url or settings.openai_base_url,
            model=settings.model_for_use_case(use_case),
            api_key=settings.openai_api_key_value,
            timeout=settings.ai_request_timeout_seconds,
        )
    return StubAIAdapter()
