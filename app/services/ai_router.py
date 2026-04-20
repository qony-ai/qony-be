from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.config import Settings
from app.integrations.ai.base import AIAdapter
from app.integrations.ai.factory import build_ai_adapter

AIUseCase = Literal["extraction", "generation", "scraping"]


@dataclass(slots=True)
class AIRouterResult:
    payload: dict[str, Any]
    provider: str
    model: str | None


class AIRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def resolve_adapter(self, *, use_case: AIUseCase) -> AIAdapter:
        return build_ai_adapter(self.settings, use_case=use_case)

    def provider_for_use_case(self, *, use_case: AIUseCase) -> str:
        return self.resolve_adapter(use_case=use_case).provider

    def model_for_use_case(self, *, use_case: AIUseCase) -> str | None:
        return self.resolve_adapter(use_case=use_case).model

    def complete_json(
        self,
        *,
        use_case: AIUseCase,
        system_prompt: str,
        user_prompt: str,
    ) -> AIRouterResult:
        adapter = self.resolve_adapter(use_case=use_case)
        payload = adapter.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        return AIRouterResult(payload=payload, provider=adapter.provider, model=adapter.model)
