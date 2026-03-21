from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field
from typing import Literal

from app.schemas.workspace import MutationCommand, PatchCommand, WorkspaceGraph


class AIInvocationResult(BaseModel):
    provider: str
    model: str
    fallback_used: bool = False
    request_log_id: UUID | None = None


class AIWorkspacePatchResponse(BaseModel):
    invocation: AIInvocationResult
    commands: list[PatchCommand] = Field(default_factory=list)
    rationale: str | None = None


class AIExportAssistResponse(BaseModel):
    invocation: AIInvocationResult
    narrative: str | None = None


class AIExecutionContext(BaseModel):
    feature: str
    project_id: UUID | None = None
    workspace_id: UUID | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class AIProviderResult(BaseModel):
    provider: str
    model: str | None = None
    payload: dict[str, object]
    fallback_used: bool = False
    request_log_id: UUID | None = None


class IngestGraphSuggestion(BaseModel):
    graph: WorkspaceGraph
    provider_result: AIProviderResult


class MutationPatchSuggestion(BaseModel):
    commands: list[PatchCommand]
    provider_result: AIProviderResult
    summary: str | None = None


class WorkspaceGraphRewriteSuggestion(BaseModel):
    action: Literal["explain", "rewrite_graph"] = "rewrite_graph"
    graph: WorkspaceGraph | None = None
    provider_result: AIProviderResult
    summary: str | None = None
    request_payload: dict[str, object] = Field(default_factory=dict)
    response_payload: dict[str, object] = Field(default_factory=dict)
