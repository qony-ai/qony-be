"""Admin endpoints.

Mounted under ``/api/v1/admin`` and gated by :func:`app.api.deps.require_admin`
(an ``"admin"`` entry in the actor's entitlement tuple). These endpoints
back the Phase 2 admin dashboard; they are skeletons in Phase 1:

* ``GET /feature-flags`` returns the merged defaults + runtime overrides.
* ``PUT /feature-flags/{key}`` flips a flag for the running process.
* ``DELETE /feature-flags/{key}`` reverts a flag back to its default.
* ``GET /usage/me`` returns the caller's own month-to-date usage against
  plan limits (useful for smoke-testing the metering pipeline).
* ``GET /health`` summarises runtime config (AI provider, env, key flags).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_feature_flags_service,
    get_settings,
    get_usage_service,
    require_admin,
)
from app.core.config import Settings
from app.core.exceptions import DomainValidationError
from app.core.limits import get_limits
from app.core.security import Actor
from app.schemas.admin import (
    AdminHealthPayload,
    FeatureFlagUpdateRequest,
    FeatureFlagsPayload,
    UsageSummaryPayload,
)
from app.schemas.common import ApiEnvelope
from app.services.feature_flags_service import FeatureFlagsService
from app.services.usage_service import UsageService

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


# ------------------------------------------------------------- feature flags


@router.get("/feature-flags", response_model=ApiEnvelope[FeatureFlagsPayload])
def list_feature_flags(
    service: FeatureFlagsService = Depends(get_feature_flags_service),
) -> ApiEnvelope[FeatureFlagsPayload]:
    return ApiEnvelope(data=FeatureFlagsPayload(flags=service.list_flags()))


@router.put("/feature-flags/{key}", response_model=ApiEnvelope[FeatureFlagsPayload])
def set_feature_flag(
    key: str,
    body: FeatureFlagUpdateRequest,
    service: FeatureFlagsService = Depends(get_feature_flags_service),
) -> ApiEnvelope[FeatureFlagsPayload]:
    if not key.strip():
        raise DomainValidationError("Feature flag key must not be blank.")
    flags = service.set_flag(key, body.value)
    return ApiEnvelope(data=FeatureFlagsPayload(flags=flags))


@router.delete("/feature-flags/{key}", response_model=ApiEnvelope[FeatureFlagsPayload])
def reset_feature_flag(
    key: str,
    service: FeatureFlagsService = Depends(get_feature_flags_service),
) -> ApiEnvelope[FeatureFlagsPayload]:
    flags = service.reset_flag(key)
    return ApiEnvelope(data=FeatureFlagsPayload(flags=flags))


# -------------------------------------------------------------------- usage


@router.get("/usage/me", response_model=ApiEnvelope[UsageSummaryPayload])
def my_usage(
    actor: Actor = Depends(require_admin),
    service: UsageService = Depends(get_usage_service),
) -> ApiEnvelope[UsageSummaryPayload]:
    user = service._current_user()  # noqa: SLF001 — admin endpoint, safe to reach in
    tier = service._resolve_tier(user)  # noqa: SLF001
    limits = dict(get_limits(tier))
    usage = service.monthly_usage(user_id=user.id)
    return ApiEnvelope(
        data=UsageSummaryPayload(
            plan_tier=tier,
            limits=limits,
            usage=usage,
        )
    )


# ------------------------------------------------------------------- health


@router.get("/health", response_model=ApiEnvelope[AdminHealthPayload])
def admin_health(
    settings: Settings = Depends(get_settings),
    feature_flags: FeatureFlagsService = Depends(get_feature_flags_service),
) -> ApiEnvelope[AdminHealthPayload]:
    flags = feature_flags.list_flags()
    return ApiEnvelope(
        data=AdminHealthPayload(
            status="ok",
            environment=settings.environment,
            ai_provider=settings.ai_provider,
            export_engine_enabled=bool(flags.get("export_engine_enabled")),
        )
    )
