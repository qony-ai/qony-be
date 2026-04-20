from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_admin_service
from app.schemas.admin import AdminMetricsRead, AdminUserRead, FeatureFlagList
from app.schemas.common import ApiEnvelope
from app.services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=ApiEnvelope[list[AdminUserRead]])
async def list_users(
    service: AdminService = Depends(get_admin_service),
) -> ApiEnvelope[list[AdminUserRead]]:
    return ApiEnvelope(data=service.list_users())


@router.get("/metrics", response_model=ApiEnvelope[AdminMetricsRead])
async def get_metrics(
    service: AdminService = Depends(get_admin_service),
) -> ApiEnvelope[AdminMetricsRead]:
    return ApiEnvelope(data=service.metrics())


@router.get("/flags", response_model=ApiEnvelope[FeatureFlagList])
async def get_flags(
    service: AdminService = Depends(get_admin_service),
) -> ApiEnvelope[FeatureFlagList]:
    return ApiEnvelope(data=service.flags())
