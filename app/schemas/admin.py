"""Admin API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FeatureFlagsPayload(BaseModel):
    flags: dict[str, bool]


class FeatureFlagUpdateRequest(BaseModel):
    value: bool


class UsageSummaryPayload(BaseModel):
    plan_tier: str
    limits: dict[str, int | None] = Field(default_factory=dict)
    usage: dict[str, int] = Field(default_factory=dict)


class AdminHealthPayload(BaseModel):
    status: str
    environment: str
    ai_provider: str
    export_engine_enabled: bool
