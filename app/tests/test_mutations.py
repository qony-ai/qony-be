from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.exceptions import DomainValidationError
from app.domain.enums import EdgeType, NodeSource, NodeType
from app.domain.graph import ensure_valid_graph
from app.domain.mutations import apply_mutation_commands
from app.schemas.workspace import (
    AddEdgeCommand,
    AddNodeCommand,
    ApplyAIPatchCommand,
    DeleteNodeCommand,
    EdgeDraft,
    GraphMetadata,
    GraphNode,
    GraphValidationSummary,
    MoveNodeCommand,
    NodeDraft,
    Position,
    UpdateNodeCommand,
    WorkspaceGraph,
)


def _base_graph() -> WorkspaceGraph:
    now = datetime.now(UTC)
    root = GraphNode(
        id=uuid4(),
        type=NodeType.PROBLEM,
        title="Primary problem",
        description="Root problem statement",
        source=NodeSource.USER,
        is_enrichment=False,
        source_url=None,
        confidence=1.0,
        position=Position(x=0, y=0),
        metadata={},
        created_at=now,
        updated_at=now,
    )
    return WorkspaceGraph(
        nodes=[root],
        edges=[],
        metadata=GraphMetadata(
            project_id=uuid4(),
            workspace_id=uuid4(),
            version=1,
            updated_at=now,
            validation=GraphValidationSummary(is_valid=True),
            attributes={},
        ),
    )


def test_mutation_engine_applies_add_node_and_edge():
    graph = _base_graph()
    root = graph.nodes[0]
    child_id = uuid4()
    mutated, applied_commands, ai_commands_applied = apply_mutation_commands(
        graph,
        [
            AddNodeCommand(
                type="add_node",
                node=NodeDraft(
                    id=child_id,
                    type=NodeType.SOLUTION,
                    title="Automate reorder",
                    description="Automated replenishment policy for fast-moving SKUs",
                    source=NodeSource.USER,
                    position=Position(x=200, y=100),
                    metadata={},
                ),
            ),
            AddEdgeCommand(
                type="add_edge",
                edge=EdgeDraft(
                    type=EdgeType.AFFECTS,
                    source=child_id,
                    target=root.id,
                    label=None,
                    metadata={},
                ),
            ),
        ],
    )

    summary = ensure_valid_graph(mutated)

    assert summary.is_valid is True
    assert applied_commands == ["add_node", "add_edge"]
    assert ai_commands_applied == 0


def test_mutation_engine_allows_many_edges_from_one_node():
    graph = _base_graph()
    root = graph.nodes[0]
    solution_id = uuid4()
    risk_id = uuid4()

    mutated, _, _ = apply_mutation_commands(
        graph,
        [
            AddNodeCommand(
                type="add_node",
                node=NodeDraft(
                    id=solution_id,
                    type=NodeType.SOLUTION,
                    title="Solution",
                    description="Proposed solution",
                    metadata={"branch_index": 0},
                ),
            ),
            AddNodeCommand(
                type="add_node",
                node=NodeDraft(
                    id=risk_id,
                    type=NodeType.RISK,
                    title="Risk",
                    description="Adoption risk",
                    metadata={"branch_index": 1},
                ),
            ),
            AddEdgeCommand(
                type="add_edge",
                edge=EdgeDraft(type=EdgeType.AFFECTS, source=solution_id, target=root.id),
            ),
            AddEdgeCommand(
                type="add_edge",
                edge=EdgeDraft(type=EdgeType.AFFECTS, source=risk_id, target=root.id),
            ),
        ],
    )

    summary = ensure_valid_graph(mutated)

    assert summary.is_valid is True
    assert len([edge for edge in mutated.edges if edge.target == root.id]) == 2


def test_mutation_engine_rejects_oversized_ai_patch():
    graph = _base_graph()

    with pytest.raises(DomainValidationError):
        apply_mutation_commands(
            graph,
            [
                ApplyAIPatchCommand(
                    type="apply_ai_patch",
                    commands=[
                        DeleteNodeCommand(type="delete_node", node_id=uuid4())
                        for _ in range(30)
                    ],
                )
            ],
            ai_command_limit=5,
        )


def test_update_node_can_change_type_title_description_and_metadata():
    graph = _base_graph()
    root = graph.nodes[0]

    mutated, _, _ = apply_mutation_commands(
        graph,
        [
            UpdateNodeCommand(
                type="update_node",
                node_id=root.id,
                node_type=NodeType.OPPORTUNITY,
                title="Opportunity: inventory visibility",
                description="Reframe stockout as an opportunity for operational lift",
                metadata={"reframed": True},
            ),
        ],
    )

    summary = ensure_valid_graph(mutated)
    updated = next(node for node in mutated.nodes if node.id == root.id)

    assert summary.is_valid is True
    assert updated.type == NodeType.OPPORTUNITY
    assert updated.title.startswith("Opportunity")
    assert updated.metadata["reframed"] is True


def test_move_node_only_updates_position():
    graph = _base_graph()
    root = graph.nodes[0]
    child_id = uuid4()

    mutated, _, _ = apply_mutation_commands(
        graph,
        [
            AddNodeCommand(
                type="add_node",
                node=NodeDraft(
                    id=child_id,
                    type=NodeType.EVIDENCE,
                    title="Stockout data",
                    description="Monthly stockout logs",
                ),
            ),
            AddEdgeCommand(
                type="add_edge",
                edge=EdgeDraft(type=EdgeType.SUPPORTS, source=child_id, target=root.id),
            ),
            MoveNodeCommand(
                type="move_node",
                node_id=child_id,
                position=Position(x=400, y=20),
            ),
        ],
    )

    summary = ensure_valid_graph(mutated)
    moved = next(node for node in mutated.nodes if node.id == child_id)

    assert summary.is_valid is True
    assert moved.position.x == 400
    assert moved.position.y == 20
