from datetime import UTC, datetime
from uuid import uuid4

from app.domain.export import build_export_preview
from app.schemas.workspace import GraphEdge, GraphMetadata, GraphNode, GraphValidationSummary, Position, WorkspaceGraph


def _node(rank: int, title: str) -> GraphNode:
    now = datetime.now(UTC)
    return GraphNode(
        id=uuid4(),
        rank=rank,
        title=title,
        content=title,
        source="manual",
        position=Position(x=0, y=0),
        metadata={},
        created_at=now,
        updated_at=now,
    )


def _edge(source: GraphNode, target: GraphNode) -> GraphEdge:
    now = datetime.now(UTC)
    return GraphEdge(
        id=uuid4(),
        source=source.id,
        target=target.id,
        metadata={},
        created_at=now,
        updated_at=now,
    )


def test_export_preview_keeps_only_complete_rank_six_branches():
    root = _node(1, "Problem")
    sub_problem = _node(2, "Sub-problem")
    hypothesis = _node(3, "Hypothesis")
    framework = _node(4, "Framework")
    evidence = _node(5, "Evidence")
    synthesis = _node(6, "Synthesis")
    incomplete_branch = _node(2, "Incomplete branch")

    graph = WorkspaceGraph(
        nodes=[root, sub_problem, hypothesis, framework, evidence, synthesis, incomplete_branch],
        edges=[
            _edge(root, sub_problem),
            _edge(sub_problem, hypothesis),
            _edge(hypothesis, framework),
            _edge(framework, evidence),
            _edge(evidence, synthesis),
            _edge(root, incomplete_branch),
        ],
        metadata=GraphMetadata(
            project_id=uuid4(),
            workspace_id=uuid4(),
            version=1,
            updated_at=datetime.now(UTC),
            validation=GraphValidationSummary(is_valid=True),
            attributes={},
        ),
    )

    chains, warnings = build_export_preview(graph)

    assert warnings == []
    assert len(chains) == 1
    assert [step.rank for step in chains[0].steps] == [1, 2, 3, 4, 5, 6]
