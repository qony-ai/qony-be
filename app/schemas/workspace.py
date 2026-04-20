from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import EdgeType, NodeSource, NodeType


class Position(BaseModel):
    x: float = 0.0
    y: float = 0.0


class GraphValidationIssue(BaseModel):
    code: str
    message: str
    node_id: UUID | None = None
    edge_id: UUID | None = None


class GraphValidationSummary(BaseModel):
    is_valid: bool
    issues: list[GraphValidationIssue] = Field(default_factory=list)
    reachable_node_count: int = 0
    complete_branch_count: int = 0


class GraphNode(BaseModel):
    id: UUID
    type: NodeType
    title: str
    description: str
    source: NodeSource = NodeSource.USER
    is_enrichment: bool = False
    source_url: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    position: Position = Field(default_factory=Position)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_web_enrichment(self) -> "GraphNode":
        if self.source == NodeSource.WEB:
            if not self.is_enrichment:
                raise ValueError("Nodes with source='web' must have is_enrichment=true.")
            if not self.source_url:
                raise ValueError("Nodes with source='web' must have a source_url.")
        elif self.is_enrichment:
            raise ValueError("is_enrichment=true is only valid when source='web'.")
        return self


class GraphEdge(BaseModel):
    id: UUID
    type: EdgeType
    source: UUID
    target: UUID
    label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class GraphMetadata(BaseModel):
    project_id: UUID
    workspace_id: UUID
    version: int
    updated_at: datetime
    validation: GraphValidationSummary
    attributes: dict[str, Any] = Field(default_factory=dict)


class WorkspaceGraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    metadata: GraphMetadata


class WorkspaceChatMessageRead(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    graph_version: int | None = None
    applied_commands: list[str] = Field(default_factory=list)
    ai_request_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class WorkspaceChatState(BaseModel):
    messages: list[WorkspaceChatMessageRead] = Field(default_factory=list)


class WorkspacePayload(BaseModel):
    project_id: UUID
    workspace_id: UUID
    graph: WorkspaceGraph
    chat: WorkspaceChatState = Field(default_factory=WorkspaceChatState)


class NodeDraft(BaseModel):
    id: UUID | None = None
    type: NodeType
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=12000)
    source: NodeSource = NodeSource.USER
    is_enrichment: bool = False
    source_url: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    position: Position = Field(default_factory=Position)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Node title must not be blank.")
        return normalized

    @model_validator(mode="after")
    def validate_web_enrichment(self) -> "NodeDraft":
        if self.source == NodeSource.WEB:
            if not self.is_enrichment:
                raise ValueError("Nodes with source='web' must have is_enrichment=true.")
            if not self.source_url:
                raise ValueError("Nodes with source='web' must have a source_url.")
        elif self.is_enrichment:
            raise ValueError("is_enrichment=true is only valid when source='web'.")
        return self


class EdgeDraft(BaseModel):
    id: UUID | None = None
    type: EdgeType
    source: UUID
    target: UUID
    label: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AddNodeCommand(BaseModel):
    type: Literal["add_node"]
    node: NodeDraft


class UpdateNodeCommand(BaseModel):
    type: Literal["update_node"]
    node_id: UUID
    node_type: NodeType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=12000)
    source: NodeSource | None = None
    is_enrichment: bool | None = None
    source_url: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    position: Position | None = None
    metadata: dict[str, Any] | None = None
    merge_metadata: bool = True

    @field_validator("title")
    @classmethod
    def normalize_optional_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Node title must not be blank.")
        return normalized


class DeleteNodeCommand(BaseModel):
    type: Literal["delete_node"]
    node_id: UUID


class AddEdgeCommand(BaseModel):
    type: Literal["add_edge"]
    edge: EdgeDraft


class DeleteEdgeCommand(BaseModel):
    type: Literal["delete_edge"]
    edge_id: UUID | None = None
    source: UUID | None = None
    target: UUID | None = None

    @model_validator(mode="after")
    def validate_locator(self) -> "DeleteEdgeCommand":
        if self.edge_id is not None:
            return self
        if self.source is None or self.target is None:
            raise ValueError("Provide either edge_id or both source and target.")
        return self


class MoveNodeCommand(BaseModel):
    type: Literal["move_node"]
    node_id: UUID
    position: Position

    @model_validator(mode="after")
    def require_position(self) -> "MoveNodeCommand":
        if self.position is None:
            raise ValueError("MoveNodeCommand requires a position.")
        return self


PatchCommand = Annotated[
    AddNodeCommand
    | UpdateNodeCommand
    | DeleteNodeCommand
    | AddEdgeCommand
    | DeleteEdgeCommand
    | MoveNodeCommand,
    Field(discriminator="type"),
]


class ApplyAIPatchCommand(BaseModel):
    type: Literal["apply_ai_patch"]
    instruction: str | None = Field(default=None, min_length=5, max_length=4000)
    commands: list[PatchCommand] = Field(default_factory=list)
    audit_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("instruction")
    @classmethod
    def normalize_instruction(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_instruction_or_commands(self) -> "ApplyAIPatchCommand":
        if not self.instruction and not self.commands:
            raise ValueError("Provide instruction or commands for apply_ai_patch.")
        return self


MutationCommand = Annotated[
    PatchCommand | ApplyAIPatchCommand,
    Field(discriminator="type"),
]


class WorkspaceMutationRequest(BaseModel):
    project_id: UUID
    expected_version: int | None = None
    actor: Literal["user", "ai"] = "user"
    reason: str | None = None
    commands: list[MutationCommand] = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WorkspaceMutationResult(BaseModel):
    project_id: UUID
    workspace_id: UUID
    graph: WorkspaceGraph
    applied_commands: list[str] = Field(default_factory=list)
    ai_commands_applied: int = 0
    ai_request_id: UUID | None = None


class WorkspaceChatRequest(BaseModel):
    project_id: UUID
    message: str = Field(min_length=3, max_length=4000)
    expected_version: int | None = None
    selected_node_id: UUID | None = None

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Message must contain at least 3 non-whitespace characters.")
        return normalized


class WorkspaceChatResponse(BaseModel):
    project_id: UUID
    workspace_id: UUID
    graph: WorkspaceGraph
    chat: WorkspaceChatState
    assistant_message: WorkspaceChatMessageRead
    applied_commands: list[str] = Field(default_factory=list)
    ai_commands_applied: int = 0
    ai_request_id: UUID | None = None
