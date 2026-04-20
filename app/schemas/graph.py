from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import KnowledgeNodeSource, KnowledgeNodeType, KnowledgeRelationType


class GraphPosition(BaseModel):
    x: float = 0.0
    y: float = 0.0


class GraphNodeBase(BaseModel):
    type: KnowledgeNodeType
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    source: KnowledgeNodeSource = KnowledgeNodeSource.USER
    is_enrichment: bool = False
    source_url: str | None = Field(default=None, max_length=2048)
    position: GraphPosition = Field(default_factory=GraphPosition)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("title must not be blank")
        return normalized


class GraphNodeCreate(GraphNodeBase):
    pass


class GraphNodeUpdate(BaseModel):
    type: KnowledgeNodeType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    source: KnowledgeNodeSource | None = None
    is_enrichment: bool | None = None
    source_url: str | None = Field(default=None, max_length=2048)
    position: GraphPosition | None = None
    metadata: dict[str, Any] | None = None
    merge_metadata: bool = True


class GraphNodeRead(GraphNodeBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class GraphEdgeBase(BaseModel):
    source: UUID
    target: UUID
    relation_type: KnowledgeRelationType
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeCreate(GraphEdgeBase):
    pass


class GraphEdgeUpdate(BaseModel):
    relation_type: KnowledgeRelationType | None = None
    metadata: dict[str, Any] | None = None
    merge_metadata: bool = True


class GraphEdgeRead(GraphEdgeBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class GraphRead(BaseModel):
    id: UUID
    project_id: UUID
    nodes: list[GraphNodeRead] = Field(default_factory=list)
    edges: list[GraphEdgeRead] = Field(default_factory=list)
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphUpdateRequest(BaseModel):
    nodes: list[GraphNodeRead] = Field(default_factory=list)
    edges: list[GraphEdgeRead] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphAIEditRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)


class GraphAIEditResponse(BaseModel):
    graph: GraphRead
    summary: str
