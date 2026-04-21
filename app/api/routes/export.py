from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app.api.deps import get_export_engine, get_export_service
from app.schemas.common import ApiEnvelope
from app.schemas.export import (
    DeliverableType,
    ExportJobCreateRequest,
    ExportJobRead,
    ExportPreviewPayload,
)
from app.services.export_engine import ExportEngine
from app.services.export_service import ExportPreviewService

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/preview/{project_id}", response_model=ApiEnvelope[ExportPreviewPayload])
def get_export_preview(
    project_id: UUID,
    deliverable_type: DeliverableType = Query("pitch_deck"),
    service: ExportPreviewService = Depends(get_export_service),
) -> ApiEnvelope[ExportPreviewPayload]:
    return ApiEnvelope(
        data=service.build_preview(
            project_id,
            deliverable_type=deliverable_type,
        )
    )


@router.post("/jobs", response_model=ApiEnvelope[ExportJobRead])
def create_export_job(
    payload: ExportJobCreateRequest,
    engine: ExportEngine = Depends(get_export_engine),
) -> ApiEnvelope[ExportJobRead]:
    return ApiEnvelope(
        data=engine.create_and_run_job(
            project_id=payload.project_id,
            deliverable_type=payload.deliverable_type,
        )
    )


@router.get("/jobs/{job_id}", response_model=ApiEnvelope[ExportJobRead])
def get_export_job(
    job_id: UUID,
    engine: ExportEngine = Depends(get_export_engine),
) -> ApiEnvelope[ExportJobRead]:
    return ApiEnvelope(data=engine.get_job(job_id))


@router.get("/jobs/{job_id}/pdf")
def download_export_pdf(
    job_id: UUID,
    engine: ExportEngine = Depends(get_export_engine),
) -> FileResponse:
    pdf_path, filename = engine.get_pdf_artifact(job_id)
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=filename,
    )
