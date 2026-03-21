from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_export_service
from app.schemas.common import ApiEnvelope
from app.schemas.export import ExportPreviewPayload
from app.services.export_service import ExportPreviewService

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/preview/{project_id}", response_model=ApiEnvelope[ExportPreviewPayload])
def get_export_preview(
    project_id: UUID,
    service: ExportPreviewService = Depends(get_export_service),
) -> ApiEnvelope[ExportPreviewPayload]:
    return ApiEnvelope(data=service.build_preview(project_id))
