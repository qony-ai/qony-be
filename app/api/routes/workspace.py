from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_workspace_service
from app.schemas.common import ApiEnvelope
from app.schemas.workspace import (
    WorkspaceChatRequest,
    WorkspaceChatResponse,
    WorkspaceMutationRequest,
    WorkspaceMutationResult,
    WorkspacePayload,
)
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("/{project_id}", response_model=ApiEnvelope[WorkspacePayload])
def get_workspace(
    project_id: UUID,
    service: WorkspaceService = Depends(get_workspace_service),
) -> ApiEnvelope[WorkspacePayload]:
    return ApiEnvelope(data=service.get_workspace(project_id))


@router.patch("/mutate", response_model=ApiEnvelope[WorkspaceMutationResult])
def mutate_workspace(
    payload: WorkspaceMutationRequest,
    service: WorkspaceService = Depends(get_workspace_service),
) -> ApiEnvelope[WorkspaceMutationResult]:
    return ApiEnvelope(data=service.mutate_workspace(payload))


@router.post("/chat", response_model=ApiEnvelope[WorkspaceChatResponse])
def chat_workspace(
    payload: WorkspaceChatRequest,
    service: WorkspaceService = Depends(get_workspace_service),
) -> ApiEnvelope[WorkspaceChatResponse]:
    return ApiEnvelope(data=service.chat_workspace(payload))
