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

    chains, report, warnings = build_export_preview(graph)

    assert warnings == []
    assert len(chains) == 1
    assert [step.rank for step in chains[0].steps] == [1, 2, 3, 4, 5, 6]
    assert report is not None
    assert report.title == "Problem"
    assert len(report.sections) == 1
    assert report.sections[0].title == "Sub-problem"
    assert report.sections[0].branches[0].headline == "Synthesis"


def test_export_preview_groups_multiple_branches_under_sub_problem():
    root = _node(1, "Market entry")
    sub_problem = _node(2, "Channel strategy")
    hypothesis_a = _node(3, "Partnerships win")
    analysis_a = _node(4, "Partner landscape")
    evidence_a = _node(5, "Distributor interviews")
    synthesis_a = _node(6, "Use channel partnerships")
    hypothesis_b = _node(3, "Direct sales win")
    analysis_b = _node(4, "Unit economics")
    evidence_b = _node(5, "Pilot conversion data")
    synthesis_b = _node(6, "Phase in direct motion later")

    graph = WorkspaceGraph(
        nodes=[
            root,
            sub_problem,
            hypothesis_a,
            analysis_a,
            evidence_a,
            synthesis_a,
            hypothesis_b,
            analysis_b,
            evidence_b,
            synthesis_b,
        ],
        edges=[
            _edge(root, sub_problem),
            _edge(sub_problem, hypothesis_a),
            _edge(hypothesis_a, analysis_a),
            _edge(analysis_a, evidence_a),
            _edge(evidence_a, synthesis_a),
            _edge(sub_problem, hypothesis_b),
            _edge(hypothesis_b, analysis_b),
            _edge(analysis_b, evidence_b),
            _edge(evidence_b, synthesis_b),
        ],
        metadata=GraphMetadata(
            project_id=uuid4(),
            workspace_id=uuid4(),
            version=4,
            updated_at=datetime.now(UTC),
            validation=GraphValidationSummary(is_valid=True),
            attributes={},
        ),
    )

    _, report, warnings = build_export_preview(graph)

    assert warnings == []
    assert report is not None
    assert report.key_takeaways == [
        "Use channel partnerships",
        "Phase in direct motion later",
    ]
    assert len(report.sections) == 1
    assert report.sections[0].branch_count == 2
    assert report.sections[0].evidence_highlights == [
        "Distributor interviews",
        "Pilot conversion data",
    ]
