from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QONY_",
        extra="ignore",
    )

    app_name: str = "Qony AI API"
    app_debug: bool = False
    app_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    environment: Literal["development", "test", "staging", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    api_docs_enabled: bool = True
    database_url: str = "postgresql+psycopg://qony:qony@localhost:5432/qony"
    database_echo: bool = False
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout_seconds: int = 30
    database_pool_recycle_seconds: int = 1800
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    request_id_header: str = "X-Request-ID"
    actor_email_header: str = "X-User-Email"
    actor_name_header: str = "X-User-Name"
    internal_actor_secret: SecretStr | str | None = None
    internal_actor_issuer: str = "qony-fe"
    internal_actor_audience: str = "qony-be"
    allow_header_actor_fallback: bool | None = None
    allow_default_actor: bool | None = None
    default_user_email: str = "local@qony.ai"
    default_user_name: str = "Local Developer"
    ai_provider: Literal["stub", "ollama", "remote"] = "stub"
    ai_fallback_to_stub: bool = True
    ai_request_timeout_seconds: float = 20.0
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    remote_ai_base_url: str = "https://api.openai.com/v1"
    remote_ai_api_key: SecretStr | str | None = None
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
    def docs_enabled(self) -> bool:
        if self.environment in {"production", "staging"}:
            return self.api_docs_enabled
        return True

    @property
    def allow_default_actor_effective(self) -> bool:
        if self.environment in {"production", "staging"}:
            return False
        if self.allow_default_actor is not None:
            return self.allow_default_actor
        return self.environment in {"development", "test"}

    @property
    def allow_header_actor_fallback_effective(self) -> bool:
        if self.allow_header_actor_fallback is not None:
            return self.allow_header_actor_fallback
        return self.environment in {"development", "test"}

    @property
    def internal_actor_secret_value(self) -> str:
        if isinstance(self.internal_actor_secret, SecretStr):
            return self.internal_actor_secret.get_secret_value()
        return self.internal_actor_secret or ""

    @property
    def remote_ai_api_key_value(self) -> str:
        if isinstance(self.remote_ai_api_key, SecretStr):
            return self.remote_ai_api_key.get_secret_value()
        return self.remote_ai_api_key or ""

    @property
    def is_remote_ai_configured(self) -> bool:
        return bool(
            self.remote_ai_base_url
            and self.remote_ai_api_key_value
            and self.remote_ai_model
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
