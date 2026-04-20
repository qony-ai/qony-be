"""Flat-graph AI service shell.

This is a lean replacement for the legacy Minto/MECE AI service. The old
implementation encoded rank semantics across every public method and helper.
The new contract mirrors Qony's flat typed-graph model: node ``type`` and
edge ``type`` carry the semantics; ``rank`` is gone entirely.

All provider calls go through :mod:`app.services.ai_router` — direct
imports of any concrete adapter (OpenAI, Ollama, etc.) are disallowed by
convention. The stub provider (used by tests and local development when
``AI_PROVIDER=stub``) is fully deterministic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AIProviderError
from app.core.security import Actor
from app.domain.enums import (
    AIProviderKind,
    AIRequestOperation,
    AIRequestStatus,
    EdgeType,
    NodeSource,
    NodeType,
)
from app.domain.graph import ensure_valid_graph
from app.repositories.ai_request_logs import AIRequestLogRepository
from app.services.ai_router import get_ai_router
from app.schemas.ai import (
    AIProviderResult,
    IngestGraphSuggestion,
    MutationPatchSuggestion,
    WorkspaceGraphRewriteSuggestion,
)
from app.schemas.workspace import (
    ApplyAIPatchCommand,
    GraphEdge,
    GraphMetadata,
    GraphNode,
    GraphValidationSummary,
    PatchCommand,
    Position,
    WorkspaceGraph,
)
from app.services.deterministic_ingest import build_deterministic_ingest_graph

PATCH_COMMAND_ADAPTER = TypeAdapter(list[PatchCommand])


class AIService:
    def __init__(self, *, session: Session, settings: Settings, actor: Actor) -> None:
        self.session = session
        self.settings = settings
        self.actor = actor
        self.adapter = get_ai_router(settings)
        self.ai_log_repository = AIRequestLogRepository(session)

    # ------------------------------------------------------------------ ingest

    def generate_ingest_graph(
        self,
        *,
        project_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        raw_text: str,
        workspace_version: int,
    ) -> IngestGraphSuggestion:
        if self.settings.ai_provider == AIProviderKind.STUB:
            graph = self._build_stub_ingest_graph(
                project_id=project_id,
                workspace_id=workspace_id,
                workspace_version=workspace_version,
                raw_text=raw_text,
            )
            provider_result = self._create_ai_result(
                operation=AIRequestOperation.INGEST,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=user_id,
                provider="stub",
                model="deterministic",
                payload=graph.model_dump(mode="json"),
                fallback_used=False,
                request_text=raw_text,
                response_text=json.dumps(graph.model_dump(mode="json")),
                status=AIRequestStatus.COMPLETED,
                error_message=None,
                latency_ms=0,
            )
            return IngestGraphSuggestion(graph=graph, provider_result=provider_result)

        system_prompt = (
            "You extract a flat typed knowledge graph from a business case. "
            "Return JSON only with keys 'nodes' and 'edges'. "
            f"Node.type must be one of: {', '.join(sorted(t.value for t in NodeType))}. "
            f"Edge.type must be one of: {', '.join(sorted(t.value for t in EdgeType))}. "
            "Each node needs: key, type, title, description, source ('document' for content from the text), "
            "is_enrichment (false for document-sourced nodes), source_url (null), confidence, position, metadata. "
            "Each edge needs: source_key, target_key, type, label, metadata. "
            "There is no rank or hierarchy; relationships are encoded in edge.type."
        )
        user_prompt = raw_text

        started_at = perf_counter()
        try:
            payload = self.adapter.complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            graph = self._graph_from_ingest_payload(
                project_id=project_id,
                workspace_id=workspace_id,
                workspace_version=workspace_version,
                payload=payload,
            )
            provider_result = self._create_ai_result(
                operation=AIRequestOperation.INGEST,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=user_id,
                provider=self.adapter.provider,
                model=self.adapter.model,
                payload=payload,
                fallback_used=False,
                request_text=user_prompt,
                response_text=json.dumps(payload),
                status=AIRequestStatus.COMPLETED,
                error_message=None,
                latency_ms=self._latency_ms(started_at),
            )
            return IngestGraphSuggestion(graph=graph, provider_result=provider_result)
        except Exception as exc:
            if not self.settings.ai_fallback_to_stub:
                raise AIProviderError(
                    "Configured AI provider failed during ingest.",
                    details=str(exc),
                ) from exc
            graph = self._build_stub_ingest_graph(
                project_id=project_id,
                workspace_id=workspace_id,
                workspace_version=workspace_version,
                raw_text=raw_text,
                ingest_mode="stub_fallback",
                provider_attempted=self.adapter.provider,
            )
            provider_result = self._create_ai_result(
                operation=AIRequestOperation.INGEST,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=user_id,
                provider=self.adapter.provider,
                model=self.adapter.model,
                payload=graph.model_dump(mode="json"),
                fallback_used=True,
                request_text=user_prompt,
                response_text=json.dumps(graph.model_dump(mode="json")),
                status=AIRequestStatus.FALLBACK,
                error_message=str(exc),
                latency_ms=self._latency_ms(started_at),
            )
            return IngestGraphSuggestion(graph=graph, provider_result=provider_result)

    # -------------------------------------------------------------- mutations

    def generate_mutation_patch(
        self,
        *,
        project_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        graph: WorkspaceGraph,
        command: ApplyAIPatchCommand,
    ) -> MutationPatchSuggestion:
        instruction = command.instruction or ""

        if self.settings.ai_provider == AIProviderKind.STUB:
            commands = self._build_stub_mutation_patch(graph=graph, instruction=instruction)
            summary = self._build_mutation_summary(instruction=instruction, commands=commands)
            provider_result = self._create_ai_result(
                operation=AIRequestOperation.WORKSPACE_MUTATION,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=user_id,
                provider="stub",
                model="deterministic",
                payload={"commands": [item.model_dump(mode="json") for item in commands]},
                fallback_used=False,
                request_text=instruction,
                response_text=json.dumps(
                    {"commands": [item.model_dump(mode="json") for item in commands]}
                ),
                status=AIRequestStatus.COMPLETED,
                error_message=None,
                latency_ms=0,
            )
            return MutationPatchSuggestion(
                commands=commands,
                provider_result=provider_result,
                summary=summary,
            )

        system_prompt = (
            "You mutate a flat typed workspace graph. "
            "Return JSON only with keys 'summary' and 'commands'. "
            "Each command.type must be one of: "
            "['add_node','update_node','delete_node','add_edge','delete_edge','move_node']. "
            "Never nest apply_ai_patch. "
            f"Node.type whitelist: {', '.join(sorted(t.value for t in NodeType))}. "
            f"Edge.type whitelist: {', '.join(sorted(t.value for t in EdgeType))}. "
            "Nodes with source='web' must have is_enrichment=true and a source_url."
        )
        user_prompt = json.dumps(
            {
                "instruction": instruction,
                "graph": graph.model_dump(mode="json"),
            }
        )

        started_at = perf_counter()
        try:
            payload = self.adapter.complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            commands = PATCH_COMMAND_ADAPTER.validate_python(payload.get("commands", []))
            summary = self._coerce_summary(
                payload.get("summary"),
                instruction=instruction,
                commands=commands,
            )
            provider_result = self._create_ai_result(
                operation=AIRequestOperation.WORKSPACE_MUTATION,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=user_id,
                provider=self.adapter.provider,
                model=self.adapter.model,
                payload=payload,
                fallback_used=False,
                request_text=user_prompt,
                response_text=json.dumps(payload),
                status=AIRequestStatus.COMPLETED,
                error_message=None,
                latency_ms=self._latency_ms(started_at),
            )
            return MutationPatchSuggestion(
                commands=commands,
                provider_result=provider_result,
                summary=summary,
            )
        except Exception as exc:
            if not self.settings.ai_fallback_to_stub:
                raise AIProviderError(
                    "Configured AI provider failed during workspace mutation.",
                    details=str(exc),
                ) from exc
            commands = self._build_stub_mutation_patch(graph=graph, instruction=instruction)
            summary = self._build_mutation_summary(instruction=instruction, commands=commands)
            provider_result = self._create_ai_result(
                operation=AIRequestOperation.WORKSPACE_MUTATION,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=user_id,
                provider=self.adapter.provider,
                model=self.adapter.model,
                payload={"commands": [item.model_dump(mode="json") for item in commands]},
                fallback_used=True,
                request_text=user_prompt,
                response_text=json.dumps(
                    {"commands": [item.model_dump(mode="json") for item in commands]}
                ),
                status=AIRequestStatus.FALLBACK,
                error_message=str(exc),
                latency_ms=self._latency_ms(started_at),
            )
            return MutationPatchSuggestion(
                commands=commands,
                provider_result=provider_result,
                summary=summary,
            )

    # ---------------------------------------------------------- chat / rewrite

    def rewrite_workspace_graph(
        self,
        *,
        project_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        graph: WorkspaceGraph,
        instruction: str,
        focus_node_id: UUID | None = None,
    ) -> WorkspaceGraphRewriteSuggestion:
        request_payload = {
            "request": instruction,
            "graph": graph.model_dump(mode="json"),
            "focus_node_id": str(focus_node_id) if focus_node_id is not None else None,
        }

        if self.settings.ai_provider == AIProviderKind.STUB:
            action, rewritten_graph = self._build_stub_chat_response(
                graph=graph,
                instruction=instruction,
            )
            summary = self._build_chat_summary(
                action=action,
                instruction=instruction,
                current_graph=graph,
                rewritten_graph=rewritten_graph,
            )
            response_payload: dict[str, Any] = {"action": action, "summary": summary}
            if rewritten_graph is not None:
                response_payload["graph"] = rewritten_graph.model_dump(mode="json")
            provider_result = self._create_ai_result(
                operation=AIRequestOperation.WORKSPACE_MUTATION,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=user_id,
                provider="stub",
                model="deterministic",
                payload=response_payload,
                fallback_used=False,
                request_text=json.dumps(request_payload),
                response_text=json.dumps(response_payload),
                status=AIRequestStatus.COMPLETED,
                error_message=None,
                latency_ms=0,
            )
            return WorkspaceGraphRewriteSuggestion(
                action=action,
                graph=rewritten_graph,
                provider_result=provider_result,
                summary=summary,
                request_payload=request_payload,
                response_payload=response_payload,
            )

        system_prompt = (
            "You are editing a flat typed workspace graph. "
            "Return JSON only with keys 'action', 'summary', and optionally 'graph'. "
            "'action' must be either 'explain' (no graph change) or 'rewrite_graph' "
            "(return a full graph replacement). "
            f"Node.type whitelist: {', '.join(sorted(t.value for t in NodeType))}. "
            f"Edge.type whitelist: {', '.join(sorted(t.value for t in EdgeType))}. "
            "Preserve node ids from the input where semantically unchanged."
        )
        user_prompt = json.dumps(request_payload)

        started_at = perf_counter()
        try:
            payload = self.adapter.complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            action = self._coerce_chat_action(payload.get("action"))
            rewritten_graph: WorkspaceGraph | None = None
            if action == "rewrite_graph":
                rewritten_graph = self._graph_from_rewrite_payload(
                    current_graph=graph,
                    payload=payload,
                )
                ensure_valid_graph(rewritten_graph)
            summary = self._build_chat_summary(
                action=action,
                instruction=instruction,
                current_graph=graph,
                rewritten_graph=rewritten_graph,
                provided_summary=payload.get("summary"),
            )
            provider_result = self._create_ai_result(
                operation=AIRequestOperation.WORKSPACE_MUTATION,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=user_id,
                provider=self.adapter.provider,
                model=self.adapter.model,
                payload=payload,
                fallback_used=False,
                request_text=user_prompt,
                response_text=json.dumps(payload),
                status=AIRequestStatus.COMPLETED,
                error_message=None,
                latency_ms=self._latency_ms(started_at),
            )
            return WorkspaceGraphRewriteSuggestion(
                action=action,
                graph=rewritten_graph,
                provider_result=provider_result,
                summary=summary,
                request_payload=request_payload,
                response_payload=payload,
            )
        except Exception as exc:
            if not self.settings.ai_fallback_to_stub:
                raise AIProviderError(
                    "Configured AI provider failed during workspace chat.",
                    details=str(exc),
                ) from exc
            action, rewritten_graph = self._build_stub_chat_response(
                graph=graph,
                instruction=instruction,
            )
            summary = self._build_chat_summary(
                action=action,
                instruction=instruction,
                current_graph=graph,
                rewritten_graph=rewritten_graph,
            )
            response_payload = {"action": action, "summary": summary}
            if rewritten_graph is not None:
                response_payload["graph"] = rewritten_graph.model_dump(mode="json")
            provider_result = self._create_ai_result(
                operation=AIRequestOperation.WORKSPACE_MUTATION,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=user_id,
                provider=self.adapter.provider,
                model=self.adapter.model,
                payload=response_payload,
                fallback_used=True,
                request_text=user_prompt,
                response_text=json.dumps(response_payload),
                status=AIRequestStatus.FALLBACK,
                error_message=str(exc),
                latency_ms=self._latency_ms(started_at),
            )
            return WorkspaceGraphRewriteSuggestion(
                action=action,
                graph=rewritten_graph,
                provider_result=provider_result,
                summary=summary,
                request_payload=request_payload,
                response_payload=response_payload,
            )

    # ---------------------------------------------------------------- diff

    def build_graph_change_actions(
        self,
        *,
        current_graph: WorkspaceGraph,
        rewritten_graph: WorkspaceGraph,
    ) -> list[str]:
        current_nodes = {node.id: node for node in current_graph.nodes}
        rewritten_nodes = {node.id: node for node in rewritten_graph.nodes}
        current_ids = set(current_nodes)
        rewritten_ids = set(rewritten_nodes)

        actions: list[str] = []
        actions.extend(["delete_node"] * len(current_ids - rewritten_ids))
        actions.extend(["add_node"] * len(rewritten_ids - current_ids))
        for node_id in current_ids & rewritten_ids:
            if self._node_has_changed(current_nodes[node_id], rewritten_nodes[node_id]):
                actions.append("update_node")

        current_edges = {self._edge_signature(edge) for edge in current_graph.edges}
        rewritten_edges = {self._edge_signature(edge) for edge in rewritten_graph.edges}
        actions.extend(["delete_edge"] * len(current_edges - rewritten_edges))
        actions.extend(["add_edge"] * len(rewritten_edges - current_edges))
        return actions

    # =============================================================== helpers

    def _build_stub_ingest_graph(
        self,
        *,
        project_id: UUID,
        workspace_id: UUID,
        workspace_version: int,
        raw_text: str,
        ingest_mode: str = "stub",
        provider_attempted: str | None = None,
    ) -> WorkspaceGraph:
        return build_deterministic_ingest_graph(
            project_id=project_id,
            workspace_id=workspace_id,
            workspace_version=workspace_version,
            raw_text=raw_text,
            created_at=self._now(),
            ingest_mode=ingest_mode,
            provider_attempted=provider_attempted,
        )

    def _build_stub_mutation_patch(
        self,
        *,
        graph: WorkspaceGraph,
        instruction: str,
    ) -> list[PatchCommand]:
        """Deterministic fallback: append one ``assumption`` node summarizing the instruction.

        The legacy stub produced a rank-aware sub-problem cascade. Under the flat
        model we just add a single placeholder node the user can edit in the UI.
        """
        label = (instruction or "AI follow-up").strip()
        if len(label) > 80:
            label = label[:77].rstrip() + "..."
        if not label:
            label = "AI follow-up"

        new_node_id = uuid4()
        add_node: PatchCommand = PATCH_COMMAND_ADAPTER.validate_python(
            [
                {
                    "type": "add_node",
                    "node": {
                        "id": str(new_node_id),
                        "type": NodeType.ASSUMPTION.value,
                        "title": label,
                        "description": instruction or label,
                        "source": NodeSource.USER.value,
                        "is_enrichment": False,
                        "source_url": None,
                        "confidence": 0.5,
                        "position": {"x": 0, "y": 0},
                        "metadata": {"generator": "stub_mutation"},
                    },
                }
            ]
        )[0]

        commands: list[PatchCommand] = [add_node]

        anchor = self._pick_anchor_node(graph)
        if anchor is not None:
            add_edge = PATCH_COMMAND_ADAPTER.validate_python(
                [
                    {
                        "type": "add_edge",
                        "edge": {
                            "id": str(uuid4()),
                            "type": EdgeType.RELATED_TO.value,
                            "source": str(anchor.id),
                            "target": str(new_node_id),
                            "label": None,
                            "metadata": {"generator": "stub_mutation"},
                        },
                    }
                ]
            )[0]
            commands.append(add_edge)

        return commands

    def _build_stub_chat_response(
        self,
        *,
        graph: WorkspaceGraph,
        instruction: str,
    ) -> tuple[str, WorkspaceGraph | None]:
        """Deterministic stub: apply the stub mutation patch and return the resulting graph."""
        from app.domain.mutations import apply_mutation_commands

        commands = self._build_stub_mutation_patch(graph=graph, instruction=instruction)
        if not commands:
            return "explain", None
        rewritten_graph, _, _ = apply_mutation_commands(graph, list(commands))
        ensure_valid_graph(rewritten_graph)
        return "rewrite_graph", rewritten_graph

    def _pick_anchor_node(self, graph: WorkspaceGraph) -> GraphNode | None:
        if not graph.nodes:
            return None
        preferred_order = (
            NodeType.PROBLEM,
            NodeType.OBJECTIVE,
            NodeType.OPPORTUNITY,
        )
        for preferred in preferred_order:
            for node in graph.nodes:
                if node.type == preferred:
                    return node
        return graph.nodes[0]

    def _graph_from_ingest_payload(
        self,
        *,
        project_id: UUID,
        workspace_id: UUID,
        workspace_version: int,
        payload: dict[str, Any],
    ) -> WorkspaceGraph:
        raw_nodes = payload.get("nodes")
        raw_edges = payload.get("edges")
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            raise AIProviderError("Ingest payload must include 'nodes' and 'edges' arrays.")

        now = self._now()
        key_to_id: dict[str, UUID] = {}
        nodes: list[GraphNode] = []

        for index, item in enumerate(raw_nodes):
            if not isinstance(item, dict):
                continue
            node_id = uuid4()
            key = str(item.get("key") or node_id)
            key_to_id[key] = node_id
            try:
                node = GraphNode(
                    id=node_id,
                    type=NodeType(str(item.get("type"))),
                    title=str(item.get("title", "")).strip() or f"Node {index + 1}",
                    description=str(item.get("description", "")).strip() or str(item.get("title", "")).strip() or f"Node {index + 1}",
                    source=NodeSource(str(item.get("source", NodeSource.DOCUMENT.value))),
                    is_enrichment=bool(item.get("is_enrichment", False)),
                    source_url=item.get("source_url"),
                    confidence=float(item.get("confidence", 1.0)),
                    position=Position(
                        x=float((item.get("position") or {}).get("x", 0)),
                        y=float((item.get("position") or {}).get("y", 0)),
                    ),
                    metadata=dict(item.get("metadata") or {}),
                    created_at=now,
                    updated_at=now,
                )
            except (ValueError, ValidationError) as exc:
                raise AIProviderError(
                    "Ingest payload contained an invalid node.",
                    details=str(exc),
                ) from exc
            nodes.append(node)

        edges: list[GraphEdge] = []
        for item in raw_edges:
            if not isinstance(item, dict):
                continue
            source_key = str(item.get("source_key") or "")
            target_key = str(item.get("target_key") or "")
            source_id = key_to_id.get(source_key)
            target_id = key_to_id.get(target_key)
            if source_id is None or target_id is None:
                continue
            try:
                edge = GraphEdge(
                    id=uuid4(),
                    type=EdgeType(str(item.get("type", EdgeType.RELATED_TO.value))),
                    source=source_id,
                    target=target_id,
                    label=item.get("label"),
                    metadata=dict(item.get("metadata") or {}),
                    created_at=now,
                    updated_at=now,
                )
            except (ValueError, ValidationError) as exc:
                raise AIProviderError(
                    "Ingest payload contained an invalid edge.",
                    details=str(exc),
                ) from exc
            edges.append(edge)

        graph = WorkspaceGraph(
            nodes=nodes,
            edges=edges,
            metadata=GraphMetadata(
                project_id=project_id,
                workspace_id=workspace_id,
                version=workspace_version,
                updated_at=now,
                validation=GraphValidationSummary(is_valid=True),
                attributes={"ingest_mode": "provider"},
            ),
        )
        ensure_valid_graph(graph)
        return graph

    def _graph_from_rewrite_payload(
        self,
        *,
        current_graph: WorkspaceGraph,
        payload: dict[str, Any],
    ) -> WorkspaceGraph:
        raw_graph = payload.get("graph")
        if not isinstance(raw_graph, dict):
            raise AIProviderError("Workspace chat response did not include a graph object.")
        raw_nodes = raw_graph.get("nodes")
        raw_edges = raw_graph.get("edges")
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            raise AIProviderError("Workspace chat graph must include nodes and edges.")

        existing_nodes = {str(node.id): node for node in current_graph.nodes}
        now = self._now()
        alias_to_id: dict[str, UUID] = {}
        nodes: list[GraphNode] = []

        for item in raw_nodes:
            if not isinstance(item, dict):
                continue
            raw_id = str(item.get("id") or uuid4())
            existing = existing_nodes.get(raw_id)
            node_id = existing.id if existing is not None else uuid4()
            alias_to_id[raw_id] = node_id
            try:
                node = GraphNode(
                    id=node_id,
                    type=NodeType(str(item.get("type", existing.type.value if existing else NodeType.PROBLEM.value))),
                    title=str(item.get("title", existing.title if existing else "")).strip() or (existing.title if existing else "Untitled"),
                    description=str(
                        item.get(
                            "description",
                            existing.description if existing else item.get("title", "")
                        )
                    ).strip() or (existing.description if existing else str(item.get("title", ""))),
                    source=NodeSource(str(item.get("source", existing.source.value if existing else NodeSource.USER.value))),
                    is_enrichment=bool(item.get("is_enrichment", existing.is_enrichment if existing else False)),
                    source_url=item.get("source_url", existing.source_url if existing else None),
                    confidence=float(item.get("confidence", existing.confidence if existing else 1.0)),
                    position=Position(
                        x=float((item.get("position") or {}).get("x", existing.position.x if existing else 0)),
                        y=float((item.get("position") or {}).get("y", existing.position.y if existing else 0)),
                    ),
                    metadata=dict(item.get("metadata") or (existing.metadata if existing else {})),
                    created_at=existing.created_at if existing else now,
                    updated_at=now,
                )
            except (ValueError, ValidationError) as exc:
                raise AIProviderError(
                    "Workspace chat payload contained an invalid node.",
                    details=str(exc),
                ) from exc
            nodes.append(node)

        edges: list[GraphEdge] = []
        for item in raw_edges:
            if not isinstance(item, dict):
                continue
            source_key = str(item.get("source") or "")
            target_key = str(item.get("target") or "")
            source_id = alias_to_id.get(source_key)
            target_id = alias_to_id.get(target_key)
            if source_id is None or target_id is None:
                continue
            try:
                edge = GraphEdge(
                    id=uuid4(),
                    type=EdgeType(str(item.get("type", EdgeType.RELATED_TO.value))),
                    source=source_id,
                    target=target_id,
                    label=item.get("label"),
                    metadata=dict(item.get("metadata") or {}),
                    created_at=now,
                    updated_at=now,
                )
            except (ValueError, ValidationError) as exc:
                raise AIProviderError(
                    "Workspace chat payload contained an invalid edge.",
                    details=str(exc),
                ) from exc
            edges.append(edge)

        return WorkspaceGraph(
            nodes=nodes,
            edges=edges,
            metadata=GraphMetadata(
                project_id=current_graph.metadata.project_id,
                workspace_id=current_graph.metadata.workspace_id,
                version=current_graph.metadata.version,
                updated_at=now,
                validation=GraphValidationSummary(is_valid=True),
                attributes=dict(current_graph.metadata.attributes),
            ),
        )

    def _coerce_chat_action(self, raw_action: Any) -> str:
        if isinstance(raw_action, str) and raw_action in ("explain", "rewrite_graph"):
            return raw_action
        return "explain"

    def _coerce_summary(
        self,
        raw_summary: Any,
        *,
        instruction: str,
        commands: list[PatchCommand],
    ) -> str:
        if isinstance(raw_summary, str) and raw_summary.strip():
            return raw_summary.strip()
        return self._build_mutation_summary(instruction=instruction, commands=commands)

    def _build_mutation_summary(
        self,
        *,
        instruction: str,
        commands: list[PatchCommand],
    ) -> str:
        if not commands:
            return "No mutation commands were produced."
        counts: dict[str, int] = {}
        for command in commands:
            counts[command.type] = counts.get(command.type, 0) + 1
        parts = [f"{count} {name}" for name, count in sorted(counts.items())]
        body = ", ".join(parts)
        if instruction:
            return f"Applied {body} in response to: {instruction}"
        return f"Applied {body}."

    def _build_chat_summary(
        self,
        *,
        action: str,
        instruction: str,
        current_graph: WorkspaceGraph,
        rewritten_graph: WorkspaceGraph | None,
        provided_summary: Any = None,
    ) -> str:
        if isinstance(provided_summary, str) and provided_summary.strip():
            return provided_summary.strip()
        if action == "explain":
            return f"Explanation only; graph unchanged. Request: {instruction}" if instruction else "Explanation only; graph unchanged."
        if rewritten_graph is None:
            return "Graph rewrite requested but no graph was produced."
        delta_nodes = len(rewritten_graph.nodes) - len(current_graph.nodes)
        delta_edges = len(rewritten_graph.edges) - len(current_graph.edges)
        return (
            f"Graph rewritten (node delta={delta_nodes:+d}, edge delta={delta_edges:+d}). "
            f"Request: {instruction}"
            if instruction
            else f"Graph rewritten (node delta={delta_nodes:+d}, edge delta={delta_edges:+d})."
        )

    @staticmethod
    def _node_has_changed(current_node: GraphNode, rewritten_node: GraphNode) -> bool:
        return (
            current_node.type != rewritten_node.type
            or current_node.title != rewritten_node.title
            or current_node.description != rewritten_node.description
            or current_node.source != rewritten_node.source
            or current_node.is_enrichment != rewritten_node.is_enrichment
            or current_node.source_url != rewritten_node.source_url
            or abs(current_node.confidence - rewritten_node.confidence) > 1e-6
        )

    @staticmethod
    def _edge_signature(edge: GraphEdge) -> tuple[str, str, str, str | None]:
        return (str(edge.source), str(edge.target), edge.type.value, edge.label)

    def _create_ai_result(
        self,
        *,
        operation: str,
        project_id: UUID | None,
        workspace_id: UUID | None,
        user_id: UUID | None,
        provider: str,
        model: str | None,
        payload: dict[str, Any],
        fallback_used: bool,
        request_text: str,
        response_text: str,
        status: str,
        error_message: str | None,
        latency_ms: int,
    ) -> AIProviderResult:
        digest = hashlib.sha256(request_text.encode("utf-8")).hexdigest()
        log = self.ai_log_repository.create(
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user_id,
            operation=operation,
            provider=provider,
            model=model,
            status=status,
            fallback_used=fallback_used,
            prompt_digest=digest,
            latency_ms=latency_ms,
            request_excerpt=request_text[:1000],
            response_excerpt=response_text[:1000],
            error_message=error_message,
            metadata={"actor_email": self.actor.email},
        )
        return AIProviderResult(
            provider=provider,
            model=model,
            payload=payload,
            fallback_used=fallback_used,
            request_log_id=log.id,
        )

    @staticmethod
    def _latency_ms(started_at: float) -> int:
        return int((perf_counter() - started_at) * 1000)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)
