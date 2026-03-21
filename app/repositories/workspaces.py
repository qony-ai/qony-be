from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.edge import Edge
from app.models.node import Node
from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceGraph


class WorkspaceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_for_project(self, *, project_id: UUID, metadata: dict | None = None) -> Workspace:
        workspace = Workspace(project_id=project_id, metadata_json=metadata or {}, version=1)
        self.session.add(workspace)
        self.session.flush()
        return workspace

    def get_by_project_id(self, project_id: UUID) -> Workspace | None:
        statement = (
            select(Workspace)
            .options(selectinload(Workspace.nodes), selectinload(Workspace.edges))
            .where(Workspace.project_id == project_id)
        )
        return self.session.scalar(statement)

    def get_by_id(self, workspace_id: UUID) -> Workspace | None:
        statement = (
            select(Workspace)
            .options(selectinload(Workspace.nodes), selectinload(Workspace.edges))
            .where(Workspace.id == workspace_id)
        )
        return self.session.scalar(statement)

    def sync_graph(self, workspace: Workspace, graph: WorkspaceGraph) -> Workspace:
        existing_nodes = {node.id: node for node in workspace.nodes}
        desired_node_ids = set()

        for graph_node in graph.nodes:
            desired_node_ids.add(graph_node.id)
            node = existing_nodes.get(graph_node.id)
            if node is None:
                node = Node(
                    id=graph_node.id,
                    workspace_id=workspace.id,
                )
                self.session.add(node)
            node.rank = int(graph_node.rank)
            node.title = graph_node.title
            node.content = graph_node.content
            node.source = graph_node.source.value
            node.position_x = graph_node.position.x
            node.position_y = graph_node.position.y
            node.metadata_json = dict(graph_node.metadata)

        self.session.flush()

        existing_edges = {edge.id: edge for edge in workspace.edges}
        desired_edge_ids = set()
        for graph_edge in graph.edges:
            desired_edge_ids.add(graph_edge.id)
            edge = existing_edges.get(graph_edge.id)
            if edge is None:
                edge = Edge(
                    id=graph_edge.id,
                    workspace_id=workspace.id,
                )
                self.session.add(edge)
            edge.source_node_id = graph_edge.source
            edge.target_node_id = graph_edge.target
            edge.label = graph_edge.label
            edge.metadata_json = dict(graph_edge.metadata)

        for edge in list(workspace.edges):
            if edge.id not in desired_edge_ids:
                self.session.delete(edge)

        for node in list(workspace.nodes):
            if node.id not in desired_node_ids:
                self.session.delete(node)

        workspace.metadata_json = dict(graph.metadata.attributes)
        workspace.version += 1
        self.session.flush()
        self.session.refresh(workspace)
        return self.get_by_id(workspace.id) or workspace
