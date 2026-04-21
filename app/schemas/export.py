"""Export schemas for preview, jobs, and component-driven slide plans."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.models.export_job import ExportJob
    from app.models.export_snapshot import ExportSnapshot


DeliverableType = Literal["pitch_deck", "business_document"]
ExportJobStatus = Literal["pending", "planning", "rendering", "completed", "failed"]
ExportPreviewStatus = Literal["ready", "stub"]


# ---------------------------------------------------------------- legacy preview


class ExportPreviewPayload(BaseModel):
    snapshot_id: UUID
    project_id: UUID
    workspace_id: UUID
    project_name: str
    generated_at: datetime
    graph_version: int | None = None
    deliverable_type: DeliverableType | None = None
    manifest_version: str | None = None
    slide_plan: "SlidePlan | None" = None
    status: ExportPreviewStatus = "ready"
    warnings: list[str] = Field(default_factory=list)


def export_snapshot_to_read(snapshot: "ExportSnapshot") -> ExportPreviewPayload:
    output = snapshot.output_json or {}
    plan_payload = output.get("slide_plan")
    slide_plan: SlidePlan | None
    if isinstance(plan_payload, dict) and plan_payload.get("steps"):
        slide_plan = SlidePlan.model_validate(plan_payload)
    else:
        slide_plan = None
    return ExportPreviewPayload(
        snapshot_id=snapshot.id,
        project_id=snapshot.project_id,
        workspace_id=snapshot.workspace_id,
        project_name=output.get("project_name", "Untitled project"),
        generated_at=snapshot.created_at,
        graph_version=output.get("graph_version"),
        deliverable_type=output.get("deliverable_type"),
        manifest_version=output.get("manifest_version"),
        slide_plan=slide_plan,
        status=output.get("status", "ready"),
        warnings=list(output.get("warnings", [])),
    )


# ----------------------------------------------------------------- new engine


class SlideStep(BaseModel):
    """A single slide / section in a planned export.

    ``component_key`` must match an entry in the export-components
    manifest (``qony-fe/public/export-components/index.json``). The
    ``variables`` dict is passed as the Handlebars context when rendering.
    """

    component_key: str
    title: str
    variables: dict[str, Any] = Field(default_factory=dict)
    source_node_ids: list[UUID] = Field(default_factory=list)


class SlidePlan(BaseModel):
    deliverable_type: DeliverableType
    manifest_version: str
    steps: list[SlideStep]
    warnings: list[str] = Field(default_factory=list)


class ExportJobCreateRequest(BaseModel):
    project_id: UUID
    deliverable_type: DeliverableType


class ExportJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    workspace_id: UUID
    deliverable_type: DeliverableType
    status: ExportJobStatus
    graph_version_at_request: int | None = None
    manifest_version: str | None = None
    slide_plan: SlidePlan | None = None
    warnings: list[str] = Field(default_factory=list)
    html_artifact_path: str | None = None
    pdf_artifact_path: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


def export_job_to_read(job: "ExportJob") -> ExportJobRead:
    plan_payload = job.slide_plan_json or {}
    slide_plan: SlidePlan | None
    if plan_payload.get("steps"):
        slide_plan = SlidePlan.model_validate(plan_payload)
    else:
        slide_plan = None
    return ExportJobRead(
        id=job.id,
        project_id=job.project_id,
        workspace_id=job.workspace_id,
        deliverable_type=job.deliverable_type,
        status=job.status,
        graph_version_at_request=job.graph_version_at_request,
        manifest_version=job.manifest_version,
        slide_plan=slide_plan,
        warnings=list(job.warnings_json or []),
        html_artifact_path=job.html_artifact_path,
        pdf_artifact_path=job.pdf_artifact_path,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
