from __future__ import annotations

from app.core.config import Settings
from app.domain.enums import AIProviderKind
from app.integrations.ai.adapters import OllamaAdapter, RemoteAIAdapter, StubAIAdapter
from app.integrations.ai.base import AIAdapter


def build_ai_adapter(settings: Settings) -> AIAdapter:
    if settings.ai_provider == AIProviderKind.OLLAMA:
        return OllamaAdapter(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=settings.ai_request_timeout_seconds,
        )
    if settings.ai_provider == AIProviderKind.REMOTE:
        return RemoteAIAdapter(
            base_url=settings.remote_ai_base_url,
            model=settings.remote_ai_model,
            api_key=settings.remote_ai_api_key or "",
            timeout=settings.ai_request_timeout_seconds,
        )
    return StubAIAdapter()
