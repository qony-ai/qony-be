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


class ExportReportBranch(BaseModel):
    branch_id: str
    headline: str
    summary: str | None = None
    hypothesis: ExportStep | None = None
    analysis: ExportStep | None = None
    evidence: list[ExportStep] = Field(default_factory=list)
    synthesis: ExportStep | None = None


class ExportReportSection(BaseModel):
    section_id: str
    title: str
    overview: str | None = None
    summary: str | None = None
    branch_count: int = 0
    evidence_highlights: list[str] = Field(default_factory=list)
    synthesis_highlights: list[str] = Field(default_factory=list)
    branches: list[ExportReportBranch] = Field(default_factory=list)


class ExportReport(BaseModel):
    title: str
    subtitle: str | None = None
    summary: str | None = None
    key_takeaways: list[str] = Field(default_factory=list)
    sections: list[ExportReportSection] = Field(default_factory=list)


class ExportPreviewPayload(BaseModel):
    snapshot_id: UUID
    project_id: UUID
    workspace_id: UUID
    generated_at: datetime
    branch_count: int = 0
    graph_version: int | None = None
    template_key: str = "premium-report-v1"
    report: ExportReport | None = None
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
        graph_version=output.get("graph_version"),
        template_key=output.get("template_key", "premium-report-v1"),
        report=ExportReport.model_validate(output["report"]) if output.get("report") else None,
        chains=chains,
        narrative=output.get("narrative"),
        warnings=list(output.get("warnings", [])),
    )
