from __future__ import annotations

from app.domain.enums import NodeSource
from app.domain.graph import validate_graph
from app.models.workspace_chat_message import WorkspaceChatMessage
from app.models.workspace import Workspace
from app.schemas.workspace import (
    GraphEdge,
    GraphMetadata,
    GraphNode,
    Position,
    WorkspaceChatMessageRead,
    WorkspaceChatState,
    WorkspaceGraph,
    WorkspacePayload,
)


def workspace_to_graph(workspace: Workspace) -> WorkspaceGraph:
    nodes = sorted(
        [
            GraphNode(
                id=node.id,
                rank=node.rank,
                title=node.title,
                content=node.content,
                source=NodeSource(node.source),
                position=Position(x=node.position_x, y=node.position_y),
                metadata=node.metadata_json or {},
                created_at=node.created_at,
                updated_at=node.updated_at,
            )
            for node in workspace.nodes
        ],
        key=lambda node: (int(node.rank), node.title.lower(), str(node.id)),
    )
    edges = sorted(
        [
            GraphEdge(
                id=edge.id,
                source=edge.source_node_id,
                target=edge.target_node_id,
                label=edge.label,
                metadata=edge.metadata_json or {},
                created_at=edge.created_at,
                updated_at=edge.updated_at,
            )
            for edge in workspace.edges
        ],
        key=lambda edge: (str(edge.source), str(edge.target), str(edge.id)),
    )
    graph = WorkspaceGraph(
        nodes=nodes,
        edges=edges,
        metadata=GraphMetadata(
            project_id=workspace.project_id,
            workspace_id=workspace.id,
            version=workspace.version,
            updated_at=workspace.updated_at,
            validation={"is_valid": True},
            attributes=workspace.metadata_json or {},
        ),
    )
    graph.metadata.validation = validate_graph(graph)
    return graph


def workspace_chat_message_to_read(message: WorkspaceChatMessage) -> WorkspaceChatMessageRead:
    return WorkspaceChatMessageRead(
        id=message.id,
        role=message.role,
        content=message.content,
        graph_version=message.graph_version,
        applied_commands=list(message.applied_commands_json or []),
        ai_request_id=message.ai_request_log_id,
        metadata=message.metadata_json or {},
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


def workspace_to_payload(
    workspace: Workspace,
    *,
    chat_messages: list[WorkspaceChatMessage] | None = None,
) -> WorkspacePayload:
    graph = workspace_to_graph(workspace)
    chat_state = WorkspaceChatState(
        messages=[
            workspace_chat_message_to_read(message)
            for message in (chat_messages or [])
        ]
    )
    return WorkspacePayload(
        project_id=workspace.project_id,
        workspace_id=workspace.id,
        graph=graph,
        chat=chat_state,
    )
