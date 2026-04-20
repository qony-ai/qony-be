from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_export_engine, get_graph_engine
from app.schemas.common import ApiEnvelope
from app.schemas.graph import GraphAIEditRequest, GraphAIEditResponse, GraphRead, GraphUpdateRequest
from app.schemas.export import ExportJobRead, ExportRequest
from app.services.export_engine import ExportEngine
from app.services.graph_engine import GraphEngine

router = APIRouter(prefix="/graphs", tags=["graphs"])


@router.get("/{graph_id}", response_model=ApiEnvelope[GraphRead])
async def get_graph(
    graph_id: UUID,
    service: GraphEngine = Depends(get_graph_engine),
) -> ApiEnvelope[GraphRead]:
    return ApiEnvelope(data=service.get_graph(graph_id))


@router.put("/{graph_id}", response_model=ApiEnvelope[GraphRead])
async def update_graph(
    graph_id: UUID,
    payload: GraphUpdateRequest,
    service: GraphEngine = Depends(get_graph_engine),
) -> ApiEnvelope[GraphRead]:
    return ApiEnvelope(data=service.replace_graph(graph_id, payload))


@router.post("/{graph_id}/ai-edit", response_model=ApiEnvelope[GraphAIEditResponse])
async def ai_edit_graph(
    graph_id: UUID,
    payload: GraphAIEditRequest,
    service: GraphEngine = Depends(get_graph_engine),
) -> ApiEnvelope[GraphAIEditResponse]:
    return ApiEnvelope(data=service.ai_edit_graph(graph_id, payload.prompt))


@router.post("/{graph_id}/export", response_model=ApiEnvelope[ExportJobRead])
async def export_graph(
    graph_id: UUID,
    payload: ExportRequest,
    service: ExportEngine = Depends(get_export_engine),
) -> ApiEnvelope[ExportJobRead]:
    return ApiEnvelope(data=service.create_export(graph_id, payload))
