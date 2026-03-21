from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QONY_",
        extra="ignore",
    )

    app_name: str = "Qony AI API"
    app_debug: bool = False
    environment: Literal["development", "test", "staging", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://qony:qony@localhost:5432/qony"
    database_echo: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    request_id_header: str = "X-Request-ID"
    default_user_email: str = "local@qony.ai"
    default_user_name: str = "Local Developer"
    ai_provider: Literal["stub", "ollama", "remote"] = "stub"
    ai_fallback_to_stub: bool = True
    ai_request_timeout_seconds: float = 20.0
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    remote_ai_base_url: str = "https://api.openai.com/v1"
    remote_ai_api_key: str | None = None
    remote_ai_model: str = "gpt-4.1-mini"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                if not isinstance(parsed, list):
                    raise ValueError("QONY_CORS_ORIGINS must be a JSON array or comma-separated string")
                return [str(item) for item in parsed]
            return [item.strip() for item in stripped.split(",") if item.strip()]
        raise ValueError("Invalid cors origins value")

    @property
    def api_prefix(self) -> str:
        return self.api_v1_prefix

    @property
    def is_remote_ai_configured(self) -> bool:
        return bool(self.remote_ai_base_url and self.remote_ai_api_key and self.remote_ai_model)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
