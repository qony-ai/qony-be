from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import get_graph_engine, get_project_service
from app.schemas.common import ApiEnvelope, DeleteResult
from app.schemas.graph import GraphRead
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectDetail,
    ProjectListPayload,
    ProjectUpdateRequest,
)
from app.services.graph_engine import GraphEngine
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ApiEnvelope[ProjectListPayload])
def list_projects(service: ProjectService = Depends(get_project_service)) -> ApiEnvelope[ProjectListPayload]:
    return ApiEnvelope(data=service.list_projects())


@router.post("", response_model=ApiEnvelope[ProjectDetail], status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreateRequest,
    service: ProjectService = Depends(get_project_service),
) -> ApiEnvelope[ProjectDetail]:
    return ApiEnvelope(data=service.create_project(payload))


@router.get("/{project_id}", response_model=ApiEnvelope[ProjectDetail])
def get_project(project_id: UUID, service: ProjectService = Depends(get_project_service)) -> ApiEnvelope[ProjectDetail]:
    return ApiEnvelope(data=service.get_project(project_id))


@router.get("/{project_id}/graph", response_model=ApiEnvelope[GraphRead])
def get_project_graph(
    project_id: UUID,
    service: GraphEngine = Depends(get_graph_engine),
) -> ApiEnvelope[GraphRead]:
    return ApiEnvelope(data=service.get_graph_for_project(project_id))


@router.patch("/{project_id}", response_model=ApiEnvelope[ProjectDetail])
def update_project(
    project_id: UUID,
    payload: ProjectUpdateRequest,
    service: ProjectService = Depends(get_project_service),
) -> ApiEnvelope[ProjectDetail]:
    return ApiEnvelope(data=service.update_project(project_id, payload))


@router.delete("/{project_id}", response_model=ApiEnvelope[DeleteResult])
def delete_project(project_id: UUID, service: ProjectService = Depends(get_project_service)) -> ApiEnvelope[DeleteResult]:
    service.delete_project(project_id)
    return ApiEnvelope(data=DeleteResult())
