from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import get_graph_engine
from app.schemas.common import ApiEnvelope, DeleteResult
from app.schemas.graph import GraphEdgeCreate, GraphEdgeRead, GraphEdgeUpdate
from app.services.graph_engine import GraphEngine

router = APIRouter(prefix="/edges", tags=["edges"])


@router.post("/{graph_id}", response_model=ApiEnvelope[GraphEdgeRead], status_code=status.HTTP_201_CREATED)
async def create_edge(
    graph_id: UUID,
    payload: GraphEdgeCreate,
    service: GraphEngine = Depends(get_graph_engine),
) -> ApiEnvelope[GraphEdgeRead]:
    return ApiEnvelope(data=service.create_edge(graph_id, payload))


@router.patch("/{edge_id}", response_model=ApiEnvelope[GraphEdgeRead])
async def update_edge(
    edge_id: UUID,
    payload: GraphEdgeUpdate,
    service: GraphEngine = Depends(get_graph_engine),
) -> ApiEnvelope[GraphEdgeRead]:
    return ApiEnvelope(data=service.update_edge(edge_id, payload))


@router.delete("/{edge_id}", response_model=ApiEnvelope[DeleteResult])
async def delete_edge(
    edge_id: UUID,
    service: GraphEngine = Depends(get_graph_engine),
) -> ApiEnvelope[DeleteResult]:
    service.delete_edge(edge_id)
    return ApiEnvelope(data=DeleteResult())
