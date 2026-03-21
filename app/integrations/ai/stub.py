import hashlib
import re
from uuid import UUID, NAMESPACE_URL, uuid5

from app.domain.enums import NodeRank, NodeSource
from app.integrations.ai.base import AIProvider
from app.schemas.export import ExportChain
from app.schemas.workspace import (
    AddEdgeCommand,
    AddNodeCommand,
    EdgeDraft,
    MutationCommand,
    NodeDraft,
    Position,
    UpdateNodeCommand,
    WorkspaceGraph,
)


class StubAIProvider(AIProvider):
    provider_name = "stub"
    model_name = "deterministic-development-fallback"

    def generate_ingest_commands(
        self,
        *,
        project_id: UUID,
        raw_text: str,
    ) -> tuple[list[MutationCommand], str | None]:
        segments = _extract_segments(raw_text)
        root_id = _stable_uuid(project_id, raw_text, "root")
        commands: list[MutationCommand] = [
            AddNodeCommand(
                type="add_node",
                node=NodeDraft(
                    id=root_id,
                    rank=NodeRank.PROBLEM_STATEMENT,
                    title=_truncate_title(segments[0]),
                    content=raw_text[:600],
                    source=NodeSource.INGEST,
                    position=Position(x=0, y=0),
                    metadata={"seed": "stub"},
                ),
            )
        ]

        branch_inputs = segments[1:3] or [segments[0]]
        y_offset = 180.0
        for index, segment in enumerate(branch_inputs, start=1):
            chain = _build_stub_chain(
                project_id=project_id,
                raw_text=raw_text,
                segment=segment,
                branch_index=index,
                parent_id=root_id,
                y_offset=y_offset * index,
            )
            commands.extend(chain)

        return commands, "Deterministic fallback generated a canonical starter graph."

    def generate_workspace_patch(
        self,
        *,
        project_id: UUID,
        graph: WorkspaceGraph,
        instruction: str,
    ) -> tuple[list[MutationCommand], str | None]:
        if not graph.nodes:
            return self.generate_ingest_commands(project_id=project_id, raw_text=instruction)

        candidate = sorted(graph.nodes, key=lambda node: (node.rank, node.updated_at, str(node.id)))[-1]
        if candidate.rank == NodeRank.SYNTHESIS:
            return (
                [
                    UpdateNodeCommand(
                        type="update_node",
                        node_id=candidate.id,
                        content=_merge_content(candidate.content, instruction),
                    )
                ],
                "Fallback updated the latest synthesis node because the graph is already fully extended.",
            )

        new_rank = NodeRank(candidate.rank + 1)
        new_node_id = _stable_uuid(project_id, instruction, f"patch:{candidate.id}:{new_rank.value}")
        title = _truncate_title(instruction)
        return (
            [
                AddNodeCommand(
                    type="add_node",
                    node=NodeDraft(
                        id=new_node_id,
                        rank=new_rank,
                        title=f"{new_rank.kind.replace('_', ' ').title()}: {title}",
                        content=instruction[:500],
                        source=NodeSource.AI,
                        position=Position(
                            x=candidate.position.x + 240,
                            y=candidate.position.y + 120,
                        ),
                        metadata={"seed": "stub_patch"},
                    ),
                ),
                AddEdgeCommand(
                    type="add_edge",
                    edge=EdgeDraft(
                        source=candidate.id,
                        target=new_node_id,
                        metadata={"seed": "stub_patch"},
                    ),
                ),
            ],
            "Deterministic fallback appended a structurally valid downstream node.",
        )

    def generate_export_narrative(
        self,
        *,
        project_id: UUID,
        chains: list[ExportChain],
    ) -> str | None:
        if not chains:
            return None
        opening = chains[0].steps[0].title
        endings = ", ".join(chain.steps[-1].title for chain in chains[:3] if chain.steps)
        return f"{opening}. Recommended synthesis outcomes: {endings}."


def _extract_segments(raw_text: str) -> list[str]:
    split = [
        segment.strip(" -")
        for segment in re.split(r"[\n\r]+|(?<=[.!?])\s+", raw_text)
        if segment.strip()
    ]
    return split or ["Untitled problem statement"]


def _truncate_title(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= 90:
        return cleaned
    return f"{cleaned[:87].rstrip()}..."


def _build_stub_chain(
    *,
    project_id: UUID,
    raw_text: str,
    segment: str,
    branch_index: int,
    parent_id: UUID,
    y_offset: float,
) -> list[MutationCommand]:
    sub_problem_id = _stable_uuid(project_id, raw_text, f"sub:{branch_index}")
    hypothesis_id = _stable_uuid(project_id, raw_text, f"hyp:{branch_index}")
    framework_id = _stable_uuid(project_id, raw_text, f"framework:{branch_index}")
    evidence_id = _stable_uuid(project_id, raw_text, f"evidence:{branch_index}")
    synthesis_id = _stable_uuid(project_id, raw_text, f"synthesis:{branch_index}")
    short = _truncate_title(segment)

    return [
        AddNodeCommand(
            type="add_node",
            node=NodeDraft(
                id=sub_problem_id,
                rank=NodeRank.SUB_PROBLEM,
                title=f"Sub-problem {branch_index}: {short}",
                content=segment[:400],
                source=NodeSource.INGEST,
                position=Position(x=240, y=y_offset),
            ),
        ),
        AddEdgeCommand(
            type="add_edge",
            edge=EdgeDraft(source=parent_id, target=sub_problem_id),
        ),
        AddNodeCommand(
            type="add_node",
            node=NodeDraft(
                id=hypothesis_id,
                rank=NodeRank.HYPOTHESIS,
                title=f"Hypothesis {branch_index}: resolving this driver will change the outcome",
                content=f"Assume the issue described by '{short}' is a material driver of the root problem.",
                source=NodeSource.INGEST,
                position=Position(x=480, y=y_offset),
            ),
        ),
        AddEdgeCommand(
            type="add_edge",
            edge=EdgeDraft(source=sub_problem_id, target=hypothesis_id),
        ),
        AddNodeCommand(
            type="add_node",
            node=NodeDraft(
                id=framework_id,
                rank=NodeRank.FRAMEWORK_ANALYSIS,
                title=f"Framework {branch_index}: driver analysis",
                content="Assess magnitude, causes, constraints, and solution options for this branch.",
                source=NodeSource.INGEST,
                position=Position(x=720, y=y_offset),
            ),
        ),
        AddEdgeCommand(
            type="add_edge",
            edge=EdgeDraft(source=hypothesis_id, target=framework_id),
        ),
        AddNodeCommand(
            type="add_node",
            node=NodeDraft(
                id=evidence_id,
                rank=NodeRank.SUPPORTING_DATA,
                title=f"Evidence {branch_index}: source excerpt",
                content=segment[:500],
                source=NodeSource.INGEST,
                position=Position(x=960, y=y_offset),
            ),
        ),
        AddEdgeCommand(
            type="add_edge",
            edge=EdgeDraft(source=framework_id, target=evidence_id),
        ),
        AddNodeCommand(
            type="add_node",
            node=NodeDraft(
                id=synthesis_id,
                rank=NodeRank.SYNTHESIS,
                title=f"Synthesis {branch_index}: prioritized next action",
                content=f"Address '{short}' first, then validate impact with additional evidence.",
                source=NodeSource.INGEST,
                position=Position(x=1200, y=y_offset),
            ),
        ),
        AddEdgeCommand(
            type="add_edge",
            edge=EdgeDraft(source=evidence_id, target=synthesis_id),
        ),
    ]


def _stable_uuid(project_id: UUID, seed: str, suffix: str) -> UUID:
    digest = hashlib.sha256(f"{project_id}:{seed}:{suffix}".encode("utf-8")).hexdigest()
    return uuid5(NAMESPACE_URL, digest)


def _merge_content(existing: str | None, addition: str) -> str:
    if not existing:
        return addition[:500]
    return f"{existing.rstrip()}\n\n{addition[:500]}"

