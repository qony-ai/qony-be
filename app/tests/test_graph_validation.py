from datetime import UTC, datetime
from uuid import uuid4

from app.domain.enums import EdgeType, NodeSource, NodeType
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


def _node(
    node_type: NodeType,
    title: str,
    *,
    source: NodeSource = NodeSource.USER,
    is_enrichment: bool = False,
    source_url: str | None = None,
) -> GraphNode:
    now = datetime.now(UTC)
    return GraphNode(
        id=uuid4(),
        type=node_type,
        title=title,
        description=f"Description for {title}",
        source=source,
        is_enrichment=is_enrichment,
        source_url=source_url,
        confidence=1.0,
        position=Position(x=0, y=0),
        metadata={},
        created_at=now,
        updated_at=now,
    )


def _edge(source: GraphNode, target: GraphNode, edge_type: EdgeType = EdgeType.RELATED_TO) -> GraphEdge:
    now = datetime.now(UTC)
    return GraphEdge(
        id=uuid4(),
        type=edge_type,
        source=source.id,
        target=target.id,
        label=None,
        metadata={},
        created_at=now,
        updated_at=now,
    )


def test_validation_accepts_typed_flat_graph():
    problem = _node(NodeType.PROBLEM, "Stockouts on fast-moving SKUs")
    solution = _node(NodeType.SOLUTION, "Automated reorder policy")
    risk = _node(NodeType.RISK, "Supplier concentration")

    graph = WorkspaceGraph(
        nodes=[problem, solution, risk],
        edges=[
            _edge(solution, problem, EdgeType.AFFECTS),
            _edge(risk, solution, EdgeType.MITIGATED_BY),
        ],
        metadata=_metadata(),
    )

    summary = validate_graph(graph)

    assert summary.is_valid is True
    assert summary.reachable_node_count == 3


def test_validation_allows_feedback_loops():
    risk = _node(NodeType.RISK, "Risk")
    solution = _node(NodeType.SOLUTION, "Solution")

    graph = WorkspaceGraph(
        nodes=[risk, solution],
        edges=[
            _edge(risk, solution, EdgeType.MITIGATED_BY),
            _edge(solution, risk, EdgeType.CAUSES),
        ],
        metadata=_metadata(),
    )

    summary = validate_graph(graph)

    assert summary.is_valid is True, (
        "Feedback loops are legitimate for business case graphs and must not be blocked."
    )


def test_validation_rejects_self_loop():
    problem = _node(NodeType.PROBLEM, "Self loop")
    graph = WorkspaceGraph(
        nodes=[problem],
        edges=[_edge(problem, problem, EdgeType.CAUSES)],
        metadata=_metadata(),
    )

    summary = validate_graph(graph)

    issue_codes = {issue.code for issue in summary.issues}
    assert summary.is_valid is False
    assert "self_loop" in issue_codes


def test_validation_rejects_duplicate_edge_pair():
    problem = _node(NodeType.PROBLEM, "Problem")
    evidence = _node(NodeType.EVIDENCE, "Evidence")
    graph = WorkspaceGraph(
        nodes=[problem, evidence],
        edges=[
            _edge(evidence, problem, EdgeType.SUPPORTS),
            _edge(evidence, problem, EdgeType.SUPPORTS),
        ],
        metadata=_metadata(),
    )

    summary = validate_graph(graph)

    issue_codes = {issue.code for issue in summary.issues}
    assert summary.is_valid is False
    assert "duplicate_edge_pair" in issue_codes


def test_validation_rejects_edge_to_missing_node():
    problem = _node(NodeType.PROBLEM, "Problem")
    dangling_target_id = uuid4()
    now = datetime.now(UTC)
    graph = WorkspaceGraph(
        nodes=[problem],
        edges=[
            GraphEdge(
                id=uuid4(),
                type=EdgeType.RELATED_TO,
                source=problem.id,
                target=dangling_target_id,
                label=None,
                metadata={},
                created_at=now,
                updated_at=now,
            )
        ],
        metadata=_metadata(),
    )

    summary = validate_graph(graph)

    issue_codes = {issue.code for issue in summary.issues}
    assert summary.is_valid is False
    assert "edge_missing_endpoint" in issue_codes


def test_validation_rejects_web_node_missing_enrichment_metadata():
    # Pydantic-level validator already blocks mismatched web metadata at model construction.
    # Here we verify the domain-level check still flags any malformed node that slips through.
    now = datetime.now(UTC)
    web_node = GraphNode(
        id=uuid4(),
        type=NodeType.MARKET_DATA,
        title="Web trend",
        description="External market signal",
        source=NodeSource.WEB,
        is_enrichment=True,
        source_url="https://example.com/report",
        confidence=0.8,
        position=Position(x=0, y=0),
        metadata={},
        created_at=now,
        updated_at=now,
    )
    # Force an invalid combination after construction to exercise the domain guard.
    object.__setattr__(web_node, "source_url", None)

    graph = WorkspaceGraph(nodes=[web_node], edges=[], metadata=_metadata())
    summary = validate_graph(graph)

    issue_codes = {issue.code for issue in summary.issues}
    assert summary.is_valid is False
    assert "web_node_missing_enrichment_metadata" in issue_codes


def test_validation_allows_multi_rooted_graph():
    problem_a = _node(NodeType.PROBLEM, "Problem A")
    problem_b = _node(NodeType.PROBLEM, "Problem B")

    graph = WorkspaceGraph(
        nodes=[problem_a, problem_b],
        edges=[],
        metadata=_metadata(),
    )

    summary = validate_graph(graph)

    assert summary.is_valid is True, (
        "The flat typed model allows multiple disconnected roots; "
        "it is not an error to have more than one problem node."
    )
