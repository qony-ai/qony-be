from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_export_engine
from app.schemas.common import ApiEnvelope
from app.schemas.export import ExportJobRead
from app.services.export_engine import ExportEngine

jobs_router = APIRouter(tags=["exports"])


@jobs_router.get("/exports/{job_id}", response_model=ApiEnvelope[ExportJobRead])
async def get_export_job_prd(
    job_id: UUID,
    service: ExportEngine = Depends(get_export_engine),
) -> ApiEnvelope[ExportJobRead]:
    return ApiEnvelope(data=service.get_export_job(job_id))
