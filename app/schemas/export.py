from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import NodeRank

if TYPE_CHECKING:
    from app.models.export_snapshot import ExportSnapshot


class ExportStep(BaseModel):
    node_id: UUID
    rank: NodeRank
    kind: str
    title: str
    content: str | None = None


class ExportChain(BaseModel):
    chain_id: str
    steps: list[ExportStep] = Field(default_factory=list)


class ExportPreviewPayload(BaseModel):
    snapshot_id: UUID
    project_id: UUID
    workspace_id: UUID
    generated_at: datetime
    branch_count: int = 0
    chains: list[ExportChain] = Field(default_factory=list)
    narrative: str | None = None
    warnings: list[str] = Field(default_factory=list)


ExportPreviewData = ExportPreviewPayload


def export_snapshot_to_read(snapshot: "ExportSnapshot") -> ExportPreviewPayload:
    output = snapshot.output_json or {}
    chains = [ExportChain.model_validate(chain) for chain in output.get("chains", [])]
    return ExportPreviewPayload(
        snapshot_id=snapshot.id,
        project_id=snapshot.project_id,
        workspace_id=snapshot.workspace_id,
        generated_at=snapshot.created_at,
        branch_count=snapshot.branch_count,
        chains=chains,
        narrative=output.get("narrative"),
        warnings=list(output.get("warnings", [])),
    )
