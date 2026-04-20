from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, DomainValidationError, NotFoundError
from app.core.security import Actor
from app.domain.enums import (
    KnowledgeNodeSource,
    KnowledgeNodeType,
    KnowledgeRelationType,
    UsageEventType,
)
from app.models.edge import Edge
from app.models.node import Node
from app.models.workspace import Workspace
from app.repositories.projects import ProjectRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository
from app.schemas.graph import (
    GraphAIEditResponse,
    GraphEdgeCreate,
    GraphEdgeRead,
    GraphEdgeUpdate,
    GraphNodeCreate,
    GraphNodeRead,
    GraphNodeUpdate,
    GraphRead,
    GraphUpdateRequest,
)
from app.services.ai_router import AIRouter
from app.services.usage_service import UsageService


class GraphEngine:
    def __init__(self, *, session: Session, settings: Settings, actor: Actor) -> None:
        self.session = session
        self.settings = settings
        self.actor = actor
        self.project_repository = ProjectRepository(session)
        self.workspace_repository = WorkspaceRepository(session)
        self.user_repository = UserRepository(session)
        self.ai_router = AIRouter(settings)
        self.usage_service = UsageService(session=session, actor=actor)

    def get_graph(self, graph_id: UUID) -> GraphRead:
        workspace = self.workspace_repository.get_by_id(graph_id)
        if workspace is None:
            raise NotFoundError("Graph not found.")
        return self._workspace_to_graph(workspace)

    def get_graph_for_project(self, project_id: UUID) -> GraphRead:
        workspace = self._get_or_create_workspace_for_project(project_id)
        return self._workspace_to_graph(workspace)

    def replace_graph(self, graph_id: UUID, payload: GraphUpdateRequest) -> GraphRead:
        workspace = self.workspace_repository.get_by_id(graph_id)
        if workspace is None:
            raise NotFoundError("Graph not found.")
        self._validate_graph_payload(payload.nodes, payload.edges)
        self._sync_workspace_graph(workspace, payload.nodes, payload.edges, metadata=payload.metadata)
        self.session.commit()
        self.session.expire_all()
        refreshed = self.workspace_repository.get_by_id(graph_id)
        if refreshed is None:
            raise NotFoundError("Graph could not be reloaded after update.")
        return self._workspace_to_graph(refreshed)

    def ingest_graph(
        self,
        *,
        project_id: UUID,
        nodes: list[GraphNodeCreate],
        edges: list[GraphEdgeCreate] | None = None,
        metadata: dict | None = None,
    ) -> GraphRead:
        workspace = self._get_or_create_workspace_for_project(project_id)
        graph_nodes = [self._graph_node_read_from_create(node) for node in nodes]
        edge_payload = edges or self._build_default_edges(graph_nodes)
        graph_edges = [self._graph_edge_read_from_create(edge) for edge in edge_payload]
        self._validate_graph_payload(graph_nodes, graph_edges)
        self._sync_workspace_graph(workspace, graph_nodes, graph_edges, metadata=metadata or {})
        self.usage_service.record_event(
            event_type=UsageEventType.UPLOAD,
            project_id=project_id,
            metadata={"node_count": len(graph_nodes), "edge_count": len(graph_edges)},
        )
        self.session.commit()
        self.session.expire_all()
        refreshed = self.workspace_repository.get_by_id(workspace.id)
        if refreshed is None:
            raise NotFoundError("Graph could not be reloaded after ingest.")
        return self._workspace_to_graph(refreshed)

    def ai_edit_graph(self, graph_id: UUID, prompt: str) -> GraphAIEditResponse:
        workspace = self.workspace_repository.get_by_id(graph_id)
        if workspace is None:
            raise NotFoundError("Graph not found.")
        current_graph = self._workspace_to_graph(workspace)
        summary = "No graph changes were applied."
        next_nodes = list(current_graph.nodes)
        next_edges = list(current_graph.edges)

        lowered = prompt.lower()
        inferred_type = self._infer_type_from_prompt(lowered)
        if any(keyword in lowered for keyword in ("add ", "tambahkan", "create node", "buat node")):
            title = prompt.split(":", 1)[1].strip() if ":" in prompt else prompt.strip()
            node = GraphNodeCreate(
                type=inferred_type,
                title=title[:255] or "AI added node",
                description=f"Generated from prompt: {prompt}",
                source=KnowledgeNodeSource.USER,
                position=self._next_position(len(next_nodes)),
            )
            created_node = self._graph_node_read_from_create(node)
            next_nodes.append(created_node)
            if current_graph.nodes:
                next_edges.append(
                    self._graph_edge_read_from_create(
                        GraphEdgeCreate(
                            source=current_graph.nodes[0].id,
                            target=created_node.id,
                            relation_type=KnowledgeRelationType.RELATED_TO,
                        )
                    )
                )
            summary = f"Added a {created_node.type.value} node from the AI prompt."
        else:
            try:
                route = self.ai_router.complete_json(
                    use_case="generation",
                    system_prompt=(
                        "You edit a flat typed knowledge graph. Return JSON with optional keys "
                        "'summary' and 'nodes_to_add'. Each node_to_add item must contain "
                        "type, title, description."
                    ),
                    user_prompt=prompt,
                )
                nodes_to_add = route.payload.get("nodes_to_add", [])
                if isinstance(nodes_to_add, list):
                    for offset, item in enumerate(nodes_to_add[:3]):
                        if not isinstance(item, dict):
                            continue
                        created_node = self._graph_node_read_from_create(
                            GraphNodeCreate(
                                type=KnowledgeNodeType(str(item.get("type", inferred_type.value))),
                                title=str(item.get("title", f"AI node {offset + 1}"))[:255],
                                description=str(item.get("description", ""))[:4000] or None,
                                source=KnowledgeNodeSource.USER,
                                position=self._next_position(len(next_nodes) + offset),
                            )
                        )
                        next_nodes.append(created_node)
                    if len(next_nodes) > len(current_graph.nodes):
                        summary = str(route.payload.get("summary") or "AI added graph context.")
            except Exception:
                summary = "AI analysis completed without structured graph changes."

        graph = self.replace_graph(
            graph_id,
            GraphUpdateRequest(nodes=next_nodes, edges=next_edges, metadata=current_graph.metadata),
        )
        self.usage_service.record_event(
            event_type=UsageEventType.AI_EDIT,
            project_id=graph.project_id,
            metadata={"prompt": prompt[:300]},
        )
        self.session.commit()
        return GraphAIEditResponse(graph=graph, summary=summary)

    def create_node(self, graph_id: UUID, payload: GraphNodeCreate) -> GraphNodeRead:
        workspace = self.workspace_repository.get_by_id(graph_id)
        if workspace is None:
            raise NotFoundError("Graph not found.")
        node = Node(
            id=uuid4(),
            workspace_id=workspace.id,
            node_type=payload.type.value,
            title=payload.title,
            content=payload.description,
            source=payload.source.value,
            is_enrichment=payload.is_enrichment,
            source_url=payload.source_url,
            position_x=payload.position.x,
            position_y=payload.position.y,
            metadata_json=dict(payload.metadata),
        )
        self.session.add(node)
        workspace.version += 1
        self.session.commit()
        self.session.refresh(node)
        return self._node_to_read(node)

    def update_node(self, node_id: UUID, payload: GraphNodeUpdate) -> GraphNodeRead:
        node = self.session.get(Node, node_id)
        if node is None:
            raise NotFoundError("Node not found.")
        if payload.type is not None:
            node.node_type = payload.type.value
        if payload.title is not None:
            node.title = payload.title
        if payload.description is not None:
            node.content = payload.description
        if payload.source is not None:
            node.source = payload.source.value
        if payload.is_enrichment is not None:
            node.is_enrichment = payload.is_enrichment
        if payload.source_url is not None:
            node.source_url = payload.source_url
        if payload.position is not None:
            node.position_x = payload.position.x
            node.position_y = payload.position.y
        if payload.metadata is not None:
            node.metadata_json = (
                {**(node.metadata_json or {}), **payload.metadata}
                if payload.merge_metadata
                else dict(payload.metadata)
            )
        node.workspace.version += 1
        self.session.commit()
        self.session.refresh(node)
        return self._node_to_read(node)

    def delete_node(self, node_id: UUID) -> None:
        node = self.session.get(Node, node_id)
        if node is None:
            raise NotFoundError("Node not found.")
        node.workspace.version += 1
        self.session.delete(node)
        self.session.commit()

    def create_edge(self, graph_id: UUID, payload: GraphEdgeCreate) -> GraphEdgeRead:
        workspace = self.workspace_repository.get_by_id(graph_id)
        if workspace is None:
            raise NotFoundError("Graph not found.")
        source_node = self.session.get(Node, payload.source)
        target_node = self.session.get(Node, payload.target)
        if source_node is None or target_node is None:
            raise DomainValidationError("Edge endpoints must exist before an edge can be created.")
        if source_node.workspace_id != workspace.id or target_node.workspace_id != workspace.id:
            raise DomainValidationError("Edge endpoints must belong to the same graph.")
        edge = Edge(
            id=uuid4(),
            workspace_id=workspace.id,
            source_node_id=payload.source,
            target_node_id=payload.target,
            relation_type=payload.relation_type.value,
            label=payload.relation_type.value,
            metadata_json=dict(payload.metadata),
        )
        self.session.add(edge)
        workspace.version += 1
        self.session.commit()
        self.session.refresh(edge)
        return self._edge_to_read(edge)

    def update_edge(self, edge_id: UUID, payload: GraphEdgeUpdate) -> GraphEdgeRead:
        edge = self.session.get(Edge, edge_id)
        if edge is None:
            raise NotFoundError("Edge not found.")
        if payload.relation_type is not None:
            edge.relation_type = payload.relation_type.value
            edge.label = payload.relation_type.value
        if payload.metadata is not None:
            edge.metadata_json = (
                {**(edge.metadata_json or {}), **payload.metadata}
                if payload.merge_metadata
                else dict(payload.metadata)
            )
        edge.workspace.version += 1
        self.session.commit()
        self.session.refresh(edge)
        return self._edge_to_read(edge)

    def delete_edge(self, edge_id: UUID) -> None:
        edge = self.session.get(Edge, edge_id)
        if edge is None:
            raise NotFoundError("Edge not found.")
        edge.workspace.version += 1
        self.session.delete(edge)
        self.session.commit()

    def _validate_graph_payload(
        self,
        nodes: Iterable[GraphNodeRead],
        edges: Iterable[GraphEdgeRead],
    ) -> None:
        node_ids: set[UUID] = set()
        for node in nodes:
            if node.id in node_ids:
                raise ConflictError("Duplicate node id detected.", details={"node_id": str(node.id)})
            node_ids.add(node.id)

        seen_pairs: set[tuple[UUID, UUID, str]] = set()
        for edge in edges:
            if edge.source not in node_ids or edge.target not in node_ids:
                raise DomainValidationError("Every edge endpoint must exist in the graph.")
            if edge.source == edge.target:
                raise DomainValidationError("Self-referential edges are not allowed.")
            edge_key = (edge.source, edge.target, edge.relation_type.value)
            if edge_key in seen_pairs:
                raise ConflictError("Duplicate graph edge detected.", details={"edge": [str(edge.source), str(edge.target)]})
            seen_pairs.add(edge_key)

    def _get_or_create_workspace_for_project(self, project_id: UUID) -> Workspace:
        project = self.project_repository.get_by_id(project_id)
        if project is None:
            raise NotFoundError("Project not found.")
        workspace = self.workspace_repository.get_by_project_id(project.id)
        if workspace is None:
            workspace = self.workspace_repository.create_for_project(project_id=project.id, metadata={"graph_version": "typed-v1"})
            self.session.flush()
        return workspace

    def _workspace_to_graph(self, workspace: Workspace) -> GraphRead:
        nodes = [self._node_to_read(node) for node in workspace.nodes]
        edges = [self._edge_to_read(edge) for edge in workspace.edges]
        nodes.sort(key=lambda node: (node.created_at, node.title.lower(), str(node.id)))
        edges.sort(key=lambda edge: (edge.created_at, str(edge.source), str(edge.target)))
        metadata = {
            **(workspace.metadata_json or {}),
            "workspace_version": workspace.version,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
        return GraphRead(
            id=workspace.id,
            project_id=workspace.project_id,
            nodes=nodes,
            edges=edges,
            updated_at=workspace.updated_at,
            metadata=metadata,
        )

    def _sync_workspace_graph(
        self,
        workspace: Workspace,
        nodes: list[GraphNodeRead],
        edges: list[GraphEdgeRead],
        *,
        metadata: dict,
    ) -> None:
        existing_nodes = {node.id: node for node in workspace.nodes}
        desired_node_ids = {node.id for node in nodes}
        for payload in nodes:
            node = existing_nodes.get(payload.id)
            if node is None:
                node = Node(id=payload.id, workspace_id=workspace.id)
                self.session.add(node)
            node.node_type = payload.type.value
            node.title = payload.title
            node.content = payload.description
            node.source = payload.source.value
            node.is_enrichment = payload.is_enrichment
            node.source_url = payload.source_url
            node.position_x = payload.position.x
            node.position_y = payload.position.y
            node.metadata_json = dict(payload.metadata)
        self.session.flush()

        existing_edges = {edge.id: edge for edge in workspace.edges}
        desired_edge_ids = {edge.id for edge in edges}
        for payload in edges:
            edge = existing_edges.get(payload.id)
            if edge is None:
                edge = Edge(id=payload.id, workspace_id=workspace.id)
                self.session.add(edge)
            edge.source_node_id = payload.source
            edge.target_node_id = payload.target
            edge.relation_type = payload.relation_type.value
            edge.label = payload.relation_type.value
            edge.metadata_json = dict(payload.metadata)

        for edge in list(workspace.edges):
            if edge.id not in desired_edge_ids:
                self.session.delete(edge)

        for node in list(workspace.nodes):
            if node.id not in desired_node_ids:
                self.session.delete(node)

        workspace.version += 1
        workspace.metadata_json = {
            **(workspace.metadata_json or {}),
            **metadata,
            "graph_schema": "typed-graph-v1",
            "updated_by": self.actor.email,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self.session.flush()

    def _node_to_read(self, node: Node) -> GraphNodeRead:
        return GraphNodeRead(
            id=node.id,
            type=self._node_type_for_model(node),
            title=node.title,
            description=node.content,
            source=self._node_source_for_model(node.source),
            is_enrichment=bool(getattr(node, "is_enrichment", False)),
            source_url=getattr(node, "source_url", None),
            position={"x": node.position_x, "y": node.position_y},
            metadata=node.metadata_json or {},
            created_at=node.created_at,
            updated_at=node.updated_at,
        )

    def _edge_to_read(self, edge: Edge) -> GraphEdgeRead:
        relation_type = getattr(edge, "relation_type", None) or edge.label or KnowledgeRelationType.RELATED_TO.value
        return GraphEdgeRead(
            id=edge.id,
            source=edge.source_node_id,
            target=edge.target_node_id,
            relation_type=KnowledgeRelationType(relation_type),
            metadata=edge.metadata_json or {},
            created_at=edge.created_at,
            updated_at=edge.updated_at,
        )

    def _graph_node_read_from_create(self, payload: GraphNodeCreate) -> GraphNodeRead:
        now = datetime.now(UTC)
        return GraphNodeRead(
            id=uuid4(),
            type=payload.type,
            title=payload.title,
            description=payload.description,
            source=payload.source,
            is_enrichment=payload.is_enrichment,
            source_url=payload.source_url,
            position=payload.position,
            metadata=payload.metadata,
            created_at=now,
            updated_at=now,
        )

    def _graph_edge_read_from_create(self, payload: GraphEdgeCreate) -> GraphEdgeRead:
        now = datetime.now(UTC)
        return GraphEdgeRead(
            id=uuid4(),
            source=payload.source,
            target=payload.target,
            relation_type=payload.relation_type,
            metadata=payload.metadata,
            created_at=now,
            updated_at=now,
        )

    def _build_default_edges(self, nodes: list[GraphNodeRead]) -> list[GraphEdgeCreate]:
        if len(nodes) < 2:
            return []
        edges: list[GraphEdgeCreate] = []
        anchor = next((node for node in nodes if node.type == KnowledgeNodeType.PROBLEM), nodes[0])
        for index, node in enumerate(nodes):
            if node.id == anchor.id:
                continue
            relation = self._default_relation_for_type(node.type)
            edges.append(
                GraphEdgeCreate(
                    source=anchor.id,
                    target=node.id,
                    relation_type=relation,
                )
            )
        return edges

    def _default_relation_for_type(self, node_type: KnowledgeNodeType) -> KnowledgeRelationType:
        if node_type in {KnowledgeNodeType.METRIC}:
            return KnowledgeRelationType.MEASURED_BY
        if node_type in {KnowledgeNodeType.RISK}:
            return KnowledgeRelationType.MITIGATED_BY
        if node_type in {KnowledgeNodeType.CONSTRAINT, KnowledgeNodeType.RESOURCE}:
            return KnowledgeRelationType.REQUIRES
        if node_type in {KnowledgeNodeType.SOLUTION, KnowledgeNodeType.EVIDENCE, KnowledgeNodeType.MARKET_DATA}:
            return KnowledgeRelationType.SUPPORTS
        return KnowledgeRelationType.RELATED_TO

    def _node_type_for_model(self, node: Node) -> KnowledgeNodeType:
        try:
            return KnowledgeNodeType(node.node_type)
        except ValueError:
            return KnowledgeNodeType.PROBLEM

    def _node_source_for_model(self, raw_source: str) -> KnowledgeNodeSource:
        mapping = {
            "manual": KnowledgeNodeSource.USER,
            "user": KnowledgeNodeSource.USER,
            "ingest": KnowledgeNodeSource.DOCUMENT,
            "document": KnowledgeNodeSource.DOCUMENT,
            "ai": KnowledgeNodeSource.USER,
            "web": KnowledgeNodeSource.WEB,
        }
        return mapping.get(raw_source, KnowledgeNodeSource.USER)

    def _next_position(self, index: int) -> dict[str, float]:
        return {"x": float((index % 4) * 320), "y": float((index // 4) * 180)}

    def _infer_type_from_prompt(self, lowered_prompt: str) -> KnowledgeNodeType:
        keyword_map = {
            "problem": KnowledgeNodeType.PROBLEM,
            "solution": KnowledgeNodeType.SOLUTION,
            "assumption": KnowledgeNodeType.ASSUMPTION,
            "metric": KnowledgeNodeType.METRIC,
            "stakeholder": KnowledgeNodeType.STAKEHOLDER,
            "risk": KnowledgeNodeType.RISK,
            "opportunity": KnowledgeNodeType.OPPORTUNITY,
            "constraint": KnowledgeNodeType.CONSTRAINT,
            "evidence": KnowledgeNodeType.EVIDENCE,
            "market": KnowledgeNodeType.MARKET_DATA,
            "trend": KnowledgeNodeType.TREND,
            "competitor": KnowledgeNodeType.COMPETITOR,
            "regulation": KnowledgeNodeType.REGULATION,
            "objective": KnowledgeNodeType.OBJECTIVE,
            "resource": KnowledgeNodeType.RESOURCE,
        }
        for keyword, node_type in keyword_map.items():
            if keyword in lowered_prompt:
                return node_type
        return KnowledgeNodeType.PROBLEM
