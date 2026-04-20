from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import ExportJobStatus, ExportType
from app.models.export_job import ExportJob


class ExportRequest(BaseModel):
    export_type: ExportType


class ExportJobRead(BaseModel):
    id: UUID
    project_id: UUID
    graph_id: UUID
    export_type: ExportType
    status: ExportJobStatus
    output_url: str | None = None
    slide_plan: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


def export_job_to_read(job: ExportJob) -> ExportJobRead:
    return ExportJobRead(
        id=job.id,
        project_id=job.project_id,
        graph_id=job.workspace_id,
        export_type=ExportType(job.export_type),
        status=ExportJobStatus(job.status),
        output_url=job.output_url,
        slide_plan=job.slide_plan_json or {},
        metadata=job.metadata_json or {},
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
