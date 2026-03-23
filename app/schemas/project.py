from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import ProjectStatus

if TYPE_CHECKING:
    from app.models.project import Project


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    status: ProjectStatus = ProjectStatus.DRAFT
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Project name must not be blank.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    status: ProjectStatus | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Project name must not be blank.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_optional_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProjectSummary(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    description: str | None = None
    status: ProjectStatus
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ProjectListPayload(BaseModel):
    items: list[ProjectSummary]


class ProjectDetail(ProjectSummary):
    user_email: str
    user_name: str


ProjectCreate = ProjectCreateRequest
ProjectUpdate = ProjectUpdateRequest
ProjectRead = ProjectDetail


def project_to_summary(project: "Project") -> ProjectSummary:
    if project.workspace is None:
        raise ValueError("Project must have a canonical workspace.")
    return ProjectSummary(
        id=project.id,
        workspace_id=project.workspace.id,
        name=project.name,
        description=project.description,
        status=ProjectStatus(project.status),
        metadata=project.metadata_json or {},
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def project_to_detail(project: "Project") -> ProjectDetail:
    summary = project_to_summary(project)
    return ProjectDetail(
        **summary.model_dump(),
        user_email=project.user.email,
        user_name=project.user.name,
    )
