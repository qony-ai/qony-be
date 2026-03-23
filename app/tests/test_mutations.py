from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.exceptions import DomainValidationError
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
    WorkspaceGraph,
)


def _base_graph() -> WorkspaceGraph:
    now = datetime.now(UTC)
    root = GraphNode(
        id=uuid4(),
        rank=1,
        title="Problem",
        content="Root problem statement",
        source="manual",
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
                    rank=2,
                    title="Sub-problem",
                    content="Investigate pricing pressure",
                    source="manual",
                    position=Position(x=200, y=100),
                    metadata={},
                ),
            ),
            AddEdgeCommand(
                type="add_edge",
                edge=EdgeDraft(source=root.id, target=child_id, label=None, metadata={}),
            ),
        ],
    )

    summary = ensure_valid_graph(mutated)

    assert summary.is_valid is True
    assert applied_commands == ["add_node", "add_edge"]
    assert ai_commands_applied == 0


def test_mutation_engine_allows_one_parent_to_have_multiple_children():
    graph = _base_graph()
    root = graph.nodes[0]
    first_child_id = uuid4()
    second_child_id = uuid4()

    mutated, _, _ = apply_mutation_commands(
        graph,
        [
            AddNodeCommand(
                type="add_node",
                node=NodeDraft(
                    id=first_child_id,
                    rank=2,
                    title="Sub-problem A",
                    content="Investigate demand loss",
                    source="manual",
                    position=Position(x=200, y=0),
                    metadata={"branch_index": 0},
                ),
            ),
            AddNodeCommand(
                type="add_node",
                node=NodeDraft(
                    id=second_child_id,
                    rank=2,
                    title="Sub-problem B",
                    content="Investigate procurement bottlenecks",
                    source="manual",
                    position=Position(x=200, y=220),
                    metadata={"branch_index": 1},
                ),
            ),
            AddEdgeCommand(
                type="add_edge",
                edge=EdgeDraft(source=root.id, target=first_child_id, label=None, metadata={}),
            ),
            AddEdgeCommand(
                type="add_edge",
                edge=EdgeDraft(source=root.id, target=second_child_id, label=None, metadata={}),
            ),
        ],
    )

    summary = ensure_valid_graph(mutated)

    assert summary.is_valid is True
    assert len([edge for edge in mutated.edges if edge.source == root.id]) == 2


def test_mutation_engine_rejects_invalid_ai_patch_size():
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


def test_move_node_can_change_rank_and_position_but_requires_valid_followup_edges():
    graph = _base_graph()
    root = graph.nodes[0]
    sub_problem_id = uuid4()
    hypothesis_id = uuid4()
    mutated, _, _ = apply_mutation_commands(
        graph,
        [
            AddNodeCommand(
                type="add_node",
                node=NodeDraft(id=sub_problem_id, rank=2, title="Sub-problem", content=None, metadata={}),
            ),
            AddNodeCommand(
                type="add_node",
                node=NodeDraft(id=hypothesis_id, rank=3, title="Hypothesis", content=None, metadata={}),
            ),
            AddEdgeCommand(type="add_edge", edge=EdgeDraft(source=root.id, target=sub_problem_id, metadata={})),
            AddEdgeCommand(type="add_edge", edge=EdgeDraft(source=sub_problem_id, target=hypothesis_id, metadata={})),
            MoveNodeCommand(type="move_node", node_id=hypothesis_id, position=Position(x=400, y=20)),
        ],
    )

    summary = ensure_valid_graph(mutated)

    assert summary.is_valid is True
    moved = next(node for node in mutated.nodes if node.id == hypothesis_id)
    assert moved.position.x == 400
