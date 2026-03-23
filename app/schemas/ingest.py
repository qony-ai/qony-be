from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import IngestJobStatus
from app.schemas.workspace import WorkspaceGraph

if TYPE_CHECKING:
    from app.models.ingest_job import IngestJob


class IngestRequest(BaseModel):
    project_id: UUID
    raw_text: str = Field(min_length=10, max_length=12000)
    source_filename: str | None = Field(default=None, max_length=255)
    source_content_type: str | None = Field(default=None, max_length=255)
    replace_existing: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("raw_text")
    @classmethod
    def normalize_raw_text(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 10:
            raise ValueError("raw_text must contain at least 10 non-whitespace characters.")
        return normalized

    @field_validator("source_filename", "source_content_type")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class IngestJobRead(BaseModel):
    id: UUID
    project_id: UUID
    workspace_id: UUID
    requested_by_user_id: UUID
    status: IngestJobStatus
    provider: str
    model: str | None = None
    fallback_used: bool
    created_at: datetime
    updated_at: datetime


class IngestResponseData(BaseModel):
    job: IngestJobRead
    graph: WorkspaceGraph


IngestPayload = IngestResponseData


def ingest_job_to_read(job: "IngestJob") -> IngestJobRead:
    return IngestJobRead(
        id=job.id,
        project_id=job.project_id,
        workspace_id=job.workspace_id,
        requested_by_user_id=job.requested_by_user_id,
        status=IngestJobStatus(job.status),
        provider=job.provider,
        model=job.model,
        fallback_used=job.fallback_used,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
