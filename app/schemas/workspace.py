from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, model_validator

from app.domain.enums import MutationCommandType, NodeRank, NodeSource


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
    rank: NodeRank
    title: str
    content: str | None = None
    source: NodeSource = NodeSource.MANUAL
    position: Position = Field(default_factory=Position)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def kind(self) -> str:
        return self.rank.kind


class GraphEdge(BaseModel):
    id: UUID
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
    rank: NodeRank
    title: str = Field(min_length=1, max_length=255)
    content: str | None = Field(default=None, max_length=12000)
    source: NodeSource = NodeSource.MANUAL
    position: Position = Field(default_factory=Position)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EdgeDraft(BaseModel):
    id: UUID | None = None
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
    rank: NodeRank | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, max_length=12000)
    source: NodeSource | None = None
    position: Position | None = None
    metadata: dict[str, Any] | None = None
    merge_metadata: bool = True


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
    position: Position | None = None
    rank: NodeRank | None = None

    @model_validator(mode="after")
    def require_position_or_rank(self) -> "MoveNodeCommand":
        if self.position is None and self.rank is None:
            raise ValueError("Provide at least one of position or rank.")
        return self


PatchCommand = Annotated[
    AddNodeCommand | UpdateNodeCommand | DeleteNodeCommand | AddEdgeCommand | DeleteEdgeCommand | MoveNodeCommand,
    Field(discriminator="type"),
]


class ApplyAIPatchCommand(BaseModel):
    type: Literal["apply_ai_patch"]
    instruction: str | None = Field(default=None, min_length=5, max_length=4000)
    commands: list[PatchCommand] = Field(default_factory=list)
    audit_metadata: dict[str, Any] = Field(default_factory=dict)

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


class WorkspaceChatResponse(BaseModel):
    project_id: UUID
    workspace_id: UUID
    graph: WorkspaceGraph
    chat: WorkspaceChatState
    assistant_message: WorkspaceChatMessageRead
    applied_commands: list[str] = Field(default_factory=list)
    ai_commands_applied: int = 0
    ai_request_id: UUID | None = None
