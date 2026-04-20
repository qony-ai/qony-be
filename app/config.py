from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_prefix="QONY_",
        extra="ignore",
        populate_by_name=True,
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

    ai_mode: Literal["local", "development", "stub"] = Field(
        default="stub",
        validation_alias=AliasChoices("AI_MODE", "QONY_AI_MODE"),
    )
    ai_provider: Literal["stub", "ollama", "remote"] = "stub"
    ai_fallback_to_stub: bool = True
    ai_request_timeout_seconds: float = 20.0

    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "QONY_OLLAMA_BASE_URL"),
    )
    ollama_model: str = "qwen3:8b"
    ollama_model_extraction: str = Field(
        default="qwen3:8b",
        validation_alias=AliasChoices("OLLAMA_MODEL_EXTRACTION", "QONY_OLLAMA_MODEL_EXTRACTION"),
    )
    ollama_model_generation: str = Field(
        default="qwen3:8b",
        validation_alias=AliasChoices("OLLAMA_MODEL_GENERATION", "QONY_OLLAMA_MODEL_GENERATION"),
    )
    ollama_model_scraping: str = Field(
        default="qwen3:8b",
        validation_alias=AliasChoices("OLLAMA_MODEL_SCRAPING", "QONY_OLLAMA_MODEL_SCRAPING"),
    )

    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("OPENAI_BASE_URL", "QONY_OPENAI_BASE_URL", "QONY_REMOTE_AI_BASE_URL"),
    )
    openai_api_key: SecretStr | str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "QONY_OPENAI_API_KEY", "QONY_REMOTE_AI_API_KEY"),
    )
    openai_model_extraction: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("OPENAI_MODEL_EXTRACTION", "QONY_OPENAI_MODEL_EXTRACTION"),
    )
    openai_model_generation: str = Field(
        default="gpt-4o",
        validation_alias=AliasChoices("OPENAI_MODEL_GENERATION", "QONY_OPENAI_MODEL_GENERATION"),
    )
    openai_model_scraping: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("OPENAI_MODEL_SCRAPING", "QONY_OPENAI_MODEL_SCRAPING"),
    )

    # Backward-compatible aliases for the existing codebase.
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

    @model_validator(mode="after")
    def sync_ai_configuration(self) -> "Settings":
        mode_was_provided = "ai_mode" in self.model_fields_set
        provider_was_provided = "ai_provider" in self.model_fields_set

        if mode_was_provided:
            self.ai_provider = self._provider_for_mode(self.ai_mode)
        elif provider_was_provided:
            self.ai_mode = self._mode_for_provider(self.ai_provider)
        else:
            self.ai_mode = self._mode_for_provider(self.ai_provider)

        self.remote_ai_base_url = self.openai_base_url or self.remote_ai_base_url
        self.remote_ai_api_key = self.openai_api_key or self.remote_ai_api_key
        self.remote_ai_model = self.openai_model_generation or self.remote_ai_model

        if not self.ollama_model_extraction:
            self.ollama_model_extraction = self.ollama_model
        if not self.ollama_model_generation:
            self.ollama_model_generation = self.ollama_model
        if not self.ollama_model_scraping:
            self.ollama_model_scraping = self.ollama_model

        return self

    @staticmethod
    def _provider_for_mode(mode: str) -> Literal["stub", "ollama", "remote"]:
        return {
            "local": "ollama",
            "development": "remote",
            "stub": "stub",
        }.get(mode, "stub")

    @staticmethod
    def _mode_for_provider(provider: str) -> Literal["local", "development", "stub"]:
        return {
            "ollama": "local",
            "remote": "development",
            "stub": "stub",
        }.get(provider, "stub")

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
    def openai_api_key_value(self) -> str:
        if isinstance(self.openai_api_key, SecretStr):
            return self.openai_api_key.get_secret_value()
        if isinstance(self.remote_ai_api_key, SecretStr):
            return self.remote_ai_api_key.get_secret_value()
        return self.openai_api_key or self.remote_ai_api_key or ""

    @property
    def remote_ai_api_key_value(self) -> str:
        return self.openai_api_key_value

    @property
    def effective_ai_provider(self) -> Literal["stub", "ollama", "remote"]:
        provider = str(self.ai_provider or "stub")
        expected_provider = self._provider_for_mode(str(self.ai_mode or "stub"))
        if provider != expected_provider and provider in {"stub", "ollama", "remote"}:
            return provider
        return expected_provider

    @property
    def effective_ai_mode(self) -> Literal["local", "development", "stub"]:
        return self._mode_for_provider(self.effective_ai_provider)

    def model_for_use_case(self, use_case: Literal["extraction", "generation", "scraping"]) -> str:
        if self.effective_ai_provider == "ollama":
            return {
                "extraction": self.ollama_model_extraction or self.ollama_model,
                "generation": self.ollama_model_generation or self.ollama_model,
                "scraping": self.ollama_model_scraping or self.ollama_model,
            }[use_case]
        if self.effective_ai_provider == "remote":
            return {
                "extraction": self.openai_model_extraction or self.remote_ai_model,
                "generation": self.openai_model_generation or self.remote_ai_model,
                "scraping": self.openai_model_scraping or self.remote_ai_model,
            }[use_case]
        return "deterministic"

    @property
    def is_remote_ai_configured(self) -> bool:
        return bool(
            self.openai_base_url
            and self.openai_api_key_value
            and self.model_for_use_case("generation")
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
