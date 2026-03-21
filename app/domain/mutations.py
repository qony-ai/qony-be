from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable
from uuid import UUID, uuid4

from app.core.exceptions import DomainValidationError, NotFoundError
from app.schemas.workspace import (
    AddEdgeCommand,
    AddNodeCommand,
    ApplyAIPatchCommand,
    DeleteEdgeCommand,
    DeleteNodeCommand,
    GraphEdge,
    GraphNode,
    MoveNodeCommand,
    MutationCommand,
    PatchCommand,
    UpdateNodeCommand,
    WorkspaceGraph,
)


AICommandResolver = Callable[[WorkspaceGraph, ApplyAIPatchCommand], list[PatchCommand]]


def apply_mutation_commands(
    graph: WorkspaceGraph,
    commands: list[MutationCommand],
    *,
    ai_command_resolver: AICommandResolver | None = None,
    ai_command_limit: int = 25,
) -> tuple[WorkspaceGraph, list[str], int]:
    working = graph.model_copy(deep=True)
    applied_commands: list[str] = []
    ai_commands_applied = 0

    for command in commands:
        if isinstance(command, AddNodeCommand):
            _apply_add_node(working, command)
        elif isinstance(command, UpdateNodeCommand):
            _apply_update_node(working, command)
        elif isinstance(command, DeleteNodeCommand):
            _apply_delete_node(working, command)
        elif isinstance(command, AddEdgeCommand):
            _apply_add_edge(working, command)
        elif isinstance(command, DeleteEdgeCommand):
            _apply_delete_edge(working, command)
        elif isinstance(command, MoveNodeCommand):
            _apply_move_node(working, command)
        elif isinstance(command, ApplyAIPatchCommand):
            generated_commands: list[PatchCommand]
            if command.commands:
                generated_commands = list(command.commands)
            elif ai_command_resolver is None:
                raise DomainValidationError(
                    "AI patching is not available for this mutation request."
                )
            else:
                generated_commands = ai_command_resolver(working, command)
            if len(generated_commands) > ai_command_limit:
                raise DomainValidationError(
                    "AI-generated patch exceeded the allowed mutation command limit.",
                    details={"limit": ai_command_limit, "received": len(generated_commands)},
                )
            working, _, nested_count = apply_mutation_commands(
                working,
                generated_commands,
                ai_command_limit=ai_command_limit,
            )
            ai_commands_applied += len(generated_commands) + nested_count
        else:
            raise DomainValidationError("Unsupported mutation command received.")

        applied_commands.append(str(command.type))

    return working, applied_commands, ai_commands_applied


def _apply_add_node(graph: WorkspaceGraph, command: AddNodeCommand) -> None:
    node_id = command.node.id or uuid4()
    if any(existing.id == node_id for existing in graph.nodes):
        raise DomainValidationError(
            "Cannot add a node with a duplicate id.",
            details={"node_id": str(node_id)},
        )

    timestamp = _now()
    graph.nodes.append(
        GraphNode(
            id=node_id,
            rank=command.node.rank,
            title=command.node.title,
            content=command.node.content,
            source=command.node.source,
            position=command.node.position,
            metadata=command.node.metadata,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )


def _apply_update_node(graph: WorkspaceGraph, command: UpdateNodeCommand) -> None:
    node = _get_node(graph, command.node_id)
    if command.rank is not None:
        node.rank = command.rank
    if command.title is not None:
        node.title = command.title
    if command.content is not None:
        node.content = command.content
    if command.source is not None:
        node.source = command.source
    if command.position is not None:
        node.position = command.position
    if command.metadata is not None:
        node.metadata = (
            {**node.metadata, **command.metadata}
            if command.merge_metadata
            else dict(command.metadata)
        )
    node.updated_at = _now()


def _apply_delete_node(graph: WorkspaceGraph, command: DeleteNodeCommand) -> None:
    _get_node(graph, command.node_id)
    graph.nodes = [node for node in graph.nodes if node.id != command.node_id]
    graph.edges = [
        edge
        for edge in graph.edges
        if edge.source != command.node_id and edge.target != command.node_id
    ]


def _apply_add_edge(graph: WorkspaceGraph, command: AddEdgeCommand) -> None:
    _get_node(graph, command.edge.source)
    _get_node(graph, command.edge.target)

    edge_id = command.edge.id or uuid4()
    if any(existing.id == edge_id for existing in graph.edges):
        raise DomainValidationError(
            "Cannot add an edge with a duplicate id.",
            details={"edge_id": str(edge_id)},
        )

    timestamp = _now()
    graph.edges.append(
        GraphEdge(
            id=edge_id,
            source=command.edge.source,
            target=command.edge.target,
            label=command.edge.label,
            metadata=command.edge.metadata,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )


def _apply_delete_edge(graph: WorkspaceGraph, command: DeleteEdgeCommand) -> None:
    before_count = len(graph.edges)
    if command.edge_id is not None:
        graph.edges = [edge for edge in graph.edges if edge.id != command.edge_id]
    else:
        graph.edges = [
            edge
            for edge in graph.edges
            if not (edge.source == command.source and edge.target == command.target)
        ]
    if len(graph.edges) == before_count:
        raise NotFoundError("The requested edge could not be found.")


def _apply_move_node(graph: WorkspaceGraph, command: MoveNodeCommand) -> None:
    node = _get_node(graph, command.node_id)
    if command.position is not None:
        node.position = command.position
    if command.rank is not None:
        node.rank = command.rank
    node.updated_at = _now()


def _get_node(graph: WorkspaceGraph, node_id: UUID) -> GraphNode:
    for node in graph.nodes:
        if node.id == node_id:
            return node
    raise NotFoundError(f"Node {node_id} was not found.")


def _now() -> datetime:
    return datetime.now(UTC)
