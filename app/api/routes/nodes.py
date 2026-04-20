from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import get_graph_engine
from app.schemas.common import ApiEnvelope, DeleteResult
from app.schemas.graph import GraphNodeCreate, GraphNodeRead, GraphNodeUpdate
from app.services.graph_engine import GraphEngine

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.post("/{graph_id}", response_model=ApiEnvelope[GraphNodeRead], status_code=status.HTTP_201_CREATED)
async def create_node(
    graph_id: UUID,
    payload: GraphNodeCreate,
    service: GraphEngine = Depends(get_graph_engine),
) -> ApiEnvelope[GraphNodeRead]:
    return ApiEnvelope(data=service.create_node(graph_id, payload))


@router.patch("/{node_id}", response_model=ApiEnvelope[GraphNodeRead])
async def update_node(
    node_id: UUID,
    payload: GraphNodeUpdate,
    service: GraphEngine = Depends(get_graph_engine),
) -> ApiEnvelope[GraphNodeRead]:
    return ApiEnvelope(data=service.update_node(node_id, payload))


@router.delete("/{node_id}", response_model=ApiEnvelope[DeleteResult])
async def delete_node(
    node_id: UUID,
    service: GraphEngine = Depends(get_graph_engine),
) -> ApiEnvelope[DeleteResult]:
    service.delete_node(node_id)
    return ApiEnvelope(data=DeleteResult())
