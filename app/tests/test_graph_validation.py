from datetime import UTC, datetime
from uuid import uuid4

from app.domain.graph import validate_graph
from app.schemas.workspace import (
    GraphEdge,
    GraphMetadata,
    GraphNode,
    GraphValidationSummary,
    Position,
    WorkspaceGraph,
)


def _metadata() -> GraphMetadata:
    return GraphMetadata(
        project_id=uuid4(),
        workspace_id=uuid4(),
        version=1,
        updated_at=datetime.now(UTC),
        validation=GraphValidationSummary(is_valid=True),
        attributes={},
    )


def _node(rank: int, title: str) -> GraphNode:
    now = datetime.now(UTC)
    return GraphNode(
        id=uuid4(),
        rank=rank,
        title=title,
        content=None,
        source="manual",
        position=Position(x=0, y=0),
        metadata={},
        created_at=now,
        updated_at=now,
    )


def _edge(source, target) -> GraphEdge:
    now = datetime.now(UTC)
    return GraphEdge(
        id=uuid4(),
        source=source.id,
        target=target.id,
        metadata={},
        created_at=now,
        updated_at=now,
    )


def test_graph_validation_accepts_reachable_partial_graph():
    root = _node(1, "Problem")
    sub_problem = _node(2, "Sub-problem")
    graph = WorkspaceGraph(
        nodes=[root, sub_problem],
        edges=[_edge(root, sub_problem)],
        metadata=_metadata(),
    )

    summary = validate_graph(graph)

    assert summary.is_valid is True
    assert summary.reachable_node_count == 2
    assert summary.complete_branch_count == 0


def test_graph_validation_rejects_invalid_transition_and_cycle():
    root = _node(1, "Problem")
    hypothesis = _node(3, "Hypothesis")
    graph = WorkspaceGraph(
        nodes=[root, hypothesis],
        edges=[
            _edge(root, hypothesis),
            GraphEdge(
                id=uuid4(),
                source=hypothesis.id,
                target=root.id,
                metadata={},
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
        ],
        metadata=_metadata(),
    )

    summary = validate_graph(graph)

    issue_codes = {issue.code for issue in summary.issues}
    assert summary.is_valid is False
    assert "invalid_rank_transition" in issue_codes or "reverse_logic_flow" in issue_codes
    assert "cycle_detected" in issue_codes or "reverse_logic_flow" in issue_codes


def test_graph_validation_rejects_unreachable_rank_six_branch():
    root = _node(1, "Problem")
    synthesis = _node(6, "Synthesis")
    graph = WorkspaceGraph(nodes=[root, synthesis], edges=[], metadata=_metadata())

    summary = validate_graph(graph)

    issue_codes = {issue.code for issue in summary.issues}
    assert summary.is_valid is False
    assert "orphan_synthesis_branch" in issue_codes


def test_graph_validation_rejects_multiple_rank_one_roots():
    root_a = _node(1, "Problem A")
    root_b = _node(1, "Problem B")
    graph = WorkspaceGraph(nodes=[root_a, root_b], edges=[], metadata=_metadata())

    summary = validate_graph(graph)

    issue_codes = {issue.code for issue in summary.issues}
    assert summary.is_valid is False
    assert "multiple_rank_one_roots" in issue_codes
