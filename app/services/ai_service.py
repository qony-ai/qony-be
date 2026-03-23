from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AIProviderError
from app.core.security import Actor
from app.domain.enums import AIProviderKind, AIRequestOperation, AIRequestStatus, NodeRank, NodeSource
from app.domain.graph import ensure_valid_graph
from app.domain.mutations import apply_mutation_commands
from app.integrations.ai.factory import build_ai_adapter
from app.repositories.ai_request_logs import AIRequestLogRepository
from app.schemas.ai import (
    AIProviderResult,
    IngestGraphSuggestion,
    MutationPatchSuggestion,
    WorkspaceGraphRewriteSuggestion,
)
from app.schemas.workspace import (
    AddEdgeCommand,
    AddNodeCommand,
    ApplyAIPatchCommand,
    GraphEdge,
    GraphMetadata,
    GraphNode,
    GraphValidationSummary,
    NodeDraft,
    PatchCommand,
    Position,
    UpdateNodeCommand,
    WorkspaceGraph,
)
from app.services.deterministic_ingest import build_deterministic_ingest_graph

PATCH_COMMAND_ADAPTER = TypeAdapter(list[PatchCommand])
SECTION_HEADING_PATTERN = re.compile(r"^(?P<number>\d{1,2})[\.\)]\s+(?P<title>.+)$")
BULLET_PATTERN = re.compile(r"^(?:[\-\*\u2022]|\d+[\.\)])\s+(?P<content>.+)$")

STRATEGY_FRAMEWORKS: list[dict[str, Any]] = [
    {
        "id": "swot",
        "title": "SWOT Analysis",
        "aliases": ["swot", "wot"],
        "prompt_labels": ["Strengths", "Weaknesses", "Opportunities", "Threats"],
    },
    {
        "id": "3cs",
        "title": "3Cs Framework",
        "aliases": ["3c", "3cs", "company competitor customer"],
        "prompt_labels": ["Company", "Competitor", "Customer"],
    },
    {
        "id": "porter",
        "title": "Porter's Five Forces",
        "aliases": ["porter", "porter's five forces", "porters five forces", "five forces"],
        "prompt_labels": [
            "Threat of new entrants",
            "Supplier power",
            "Buyer power",
            "Threat of substitutes",
            "Competitive rivalry",
        ],
    },
    {
        "id": "pestel",
        "title": "PESTEL Analysis",
        "aliases": ["pestel", "pestle"],
        "prompt_labels": [
            "Political",
            "Economic",
            "Social",
            "Technological",
            "Environmental",
            "Legal",
        ],
    },
    {
        "id": "most",
        "title": "MOST",
        "aliases": ["most", "mission objectives strategies tactics"],
        "prompt_labels": ["Mission", "Objectives", "Strategies", "Tactics"],
    },
    {
        "id": "7s",
        "title": "7S McKinsey",
        "aliases": ["7s", "7s mckinsey", "mckinsey 7s"],
        "prompt_labels": ["Strategy", "Structure", "Systems", "Shared values", "Style", "Staff", "Skills"],
    },
    {
        "id": "value-chain",
        "title": "Value Chain Analysis",
        "aliases": ["value chain", "value-chain", "value chain analysis"],
        "prompt_labels": ["Primary activities", "Support activities", "Value leaks", "Improvement focus"],
    },
]


class AIService:
    def __init__(self, *, session: Session, settings: Settings, actor: Actor) -> None:
        self.session = session
        self.settings = settings
        self.actor = actor
        self.adapter = build_ai_adapter(settings)
        self.ai_log_repository = AIRequestLogRepository(session)

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
            "You structure business problem statements into a strict six-rank DAG. "
            "Return JSON only with keys nodes and edges. "
            "Each node must contain key, rank, title, content, source, position, metadata. "
            "Each edge must contain source_key, target_key, label, metadata. "
            "Use adjacent forward-only ranks 1->2->3->4->5->6."
        )
        user_prompt = raw_text
        return self._generate_ingest_with_provider(
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user_id,
            workspace_version=workspace_version,
            raw_text=raw_text,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    def generate_mutation_patch(
        self,
        *,
        project_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        graph: WorkspaceGraph,
        command: ApplyAIPatchCommand,
    ) -> MutationPatchSuggestion:
        if self.settings.ai_provider == AIProviderKind.STUB:
            commands = self._build_stub_mutation_patch(graph=graph, instruction=command.instruction or "")
            summary = self._build_mutation_summary(
                instruction=command.instruction or "",
                commands=commands,
            )
            provider_result = self._create_ai_result(
                operation=AIRequestOperation.WORKSPACE_MUTATION,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=user_id,
                provider="stub",
                model="deterministic",
                payload={"commands": [item.model_dump(mode="json") for item in commands]},
                fallback_used=False,
                request_text=command.instruction or "",
                response_text=json.dumps({"commands": [item.model_dump(mode="json") for item in commands]}),
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
            "You mutate a strict DAG workspace. Return JSON only with top-level keys summary and commands. "
            "Summary must be a short explanation of what changed in plain language. "
            "Each command must use the exact schema with type in "
            "['add_node','update_node','delete_node','add_edge','delete_edge','move_node']. "
            "Never return apply_ai_patch inside commands. Maintain valid adjacent rank transitions only."
        )
        user_prompt = json.dumps(
            {
                "instruction": command.instruction,
                "graph": graph.model_dump(mode="json"),
            }
        )
        return self._generate_mutation_with_provider(
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user_id,
            graph=graph,
            instruction=command.instruction or "",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

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
        framework = self._detect_framework_request(instruction)
        if framework is not None:
            if self._looks_like_framework_graph_request(instruction):
                rewritten_graph = self._apply_framework_to_graph(
                    graph=graph,
                    framework=framework,
                    focus_node_id=focus_node_id,
                )
                summary = self._build_framework_response(
                    framework=framework,
                    graph=rewritten_graph,
                    instruction=instruction,
                    focus_node_id=focus_node_id,
                    graph_changed=True,
                )
                response_payload: dict[str, Any] = {
                    "action": "rewrite_graph",
                    "summary": summary,
                    "graph": rewritten_graph.model_dump(mode="json"),
                }
                provider_result = self._create_ai_result(
                    operation=AIRequestOperation.WORKSPACE_MUTATION,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    provider="heuristic",
                    model="framework-router",
                    payload=response_payload,
                    fallback_used=False,
                    request_text=json.dumps(request_payload),
                    response_text=json.dumps(response_payload),
                    status=AIRequestStatus.COMPLETED,
                    error_message=None,
                    latency_ms=0,
                )
                return WorkspaceGraphRewriteSuggestion(
                    action="rewrite_graph",
                    graph=rewritten_graph,
                    provider_result=provider_result,
                    summary=summary,
                    request_payload=request_payload,
                    response_payload=response_payload,
                )

            summary = self._build_framework_response(
                framework=framework,
                graph=graph,
                instruction=instruction,
                focus_node_id=focus_node_id,
                graph_changed=False,
            )
            response_payload = {
                "action": "explain",
                "summary": summary,
            }
            provider_result = self._create_ai_result(
                operation=AIRequestOperation.WORKSPACE_MUTATION,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=user_id,
                provider="heuristic",
                model="framework-router",
                payload=response_payload,
                fallback_used=False,
                request_text=json.dumps(request_payload),
                response_text=json.dumps(response_payload),
                status=AIRequestStatus.COMPLETED,
                error_message=None,
                latency_ms=0,
            )
            return WorkspaceGraphRewriteSuggestion(
                action="explain",
                graph=None,
                provider_result=provider_result,
                summary=summary,
                request_payload=request_payload,
                response_payload=response_payload,
            )

        if self.settings.ai_provider == AIProviderKind.STUB:
            action, rewritten_graph = self._build_stub_workspace_chat_response(
                graph=graph,
                instruction=instruction,
                focus_node_id=focus_node_id,
            )
            summary = self._coerce_workspace_chat_summary(
                None,
                action=action,
                instruction=instruction,
                current_graph=graph,
                rewritten_graph=rewritten_graph,
                focus_node_id=focus_node_id,
            )
            response_payload: dict[str, Any] = {
                "action": action,
                "summary": summary,
            }
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
            "You are updating a strict six-rank DAG workspace. "
            "Return JSON only with top-level keys action, summary, and graph. "
            "action must be either 'explain' or 'rewrite_graph'. "
            "Use 'explain' when the user only asks for clarification, reasoning, or interpretation and does not request a graph mutation. "
            "If the user asks for SWOT, 3Cs, Porter's Five Forces, PESTEL, MOST, 7S McKinsey, or Value Chain without explicitly asking to edit the graph, use 'explain' and answer in that framework. "
            "Use 'rewrite_graph' when the user asks to add, update, delete, move, restructure, or otherwise modify the graph. "
            "summary must be a concise plain-language assistant reply. "
            "When action is 'explain', summary must directly answer the user's question using the graph content. "
            "Do not answer with only 'no changes' or node counts. "
            "When action is 'rewrite_graph', graph must be the entire desired final graph state after applying the request. "
            "Preserve ids for surviving nodes and edges whenever possible. "
            "graph.nodes must contain objects with id, rank, title, content, source, position, metadata. "
            "graph.edges must contain objects with id, source, target, label, metadata. "
            "Keep the DAG valid: only adjacent forward ranks, no cycles, no orphan branches, and no invalid downstream nodes after deletions. "
            "When action is 'explain', omit graph or set it to null."
        )
        user_prompt = json.dumps(request_payload)
        return self._generate_workspace_rewrite_with_provider(
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user_id,
            current_graph=graph,
            instruction=instruction,
            focus_node_id=focus_node_id,
            request_payload=request_payload,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    def _generate_ingest_with_provider(
        self,
        *,
        project_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        workspace_version: int,
        raw_text: str,
        system_prompt: str,
        user_prompt: str,
    ) -> IngestGraphSuggestion:
        started_at = perf_counter()
        try:
            payload = self.adapter.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
            graph = self._graph_from_ingest_payload(
                project_id=project_id,
                workspace_id=workspace_id,
                workspace_version=workspace_version,
                payload=payload,
                provider_name=self.adapter.provider,
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
                raise AIProviderError("Configured AI provider failed during ingest.", details=str(exc)) from exc
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

    def _generate_mutation_with_provider(
        self,
        *,
        project_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        graph: WorkspaceGraph,
        instruction: str,
        system_prompt: str,
        user_prompt: str,
    ) -> MutationPatchSuggestion:
        started_at = perf_counter()
        try:
            payload = self.adapter.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
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
                raise AIProviderError("Configured AI provider failed during workspace mutation.", details=str(exc)) from exc
            commands = self._build_stub_mutation_patch(graph=graph, instruction=instruction)
            summary = self._build_mutation_summary(
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
                payload={"commands": [item.model_dump(mode="json") for item in commands]},
                fallback_used=True,
                request_text=user_prompt,
                response_text=json.dumps({"commands": [item.model_dump(mode="json") for item in commands]}),
                status=AIRequestStatus.FALLBACK,
                error_message=str(exc),
                latency_ms=self._latency_ms(started_at),
            )
            return MutationPatchSuggestion(
                commands=commands,
                provider_result=provider_result,
                summary=summary,
            )

    def _generate_workspace_rewrite_with_provider(
        self,
        *,
        project_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        current_graph: WorkspaceGraph,
        instruction: str,
        focus_node_id: UUID | None,
        request_payload: dict[str, Any],
        system_prompt: str,
        user_prompt: str,
    ) -> WorkspaceGraphRewriteSuggestion:
        started_at = perf_counter()
        try:
            payload = self.adapter.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
            action = self._coerce_workspace_chat_action(payload.get("action"), instruction=instruction)
            rewritten_graph = None
            if action == "rewrite_graph":
                rewritten_graph = self._graph_from_workspace_rewrite_payload(
                    current_graph=current_graph,
                    payload=payload,
                )
                ensure_valid_graph(rewritten_graph)
            summary = self._coerce_workspace_chat_summary(
                self._extract_workspace_chat_summary(payload),
                action=action,
                instruction=instruction,
                current_graph=current_graph,
                rewritten_graph=rewritten_graph,
                focus_node_id=focus_node_id,
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
                raise AIProviderError("Configured AI provider failed during workspace chat.", details=str(exc)) from exc
            action, rewritten_graph = self._build_stub_workspace_chat_response(
                graph=current_graph,
                instruction=instruction,
                focus_node_id=focus_node_id,
            )
            summary = self._coerce_workspace_chat_summary(
                None,
                action=action,
                instruction=instruction,
                current_graph=current_graph,
                rewritten_graph=rewritten_graph,
                focus_node_id=focus_node_id,
            )
            response_payload: dict[str, Any] = {
                "action": action,
                "summary": summary,
            }
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

    def _normalize_ingest_paragraphs(self, raw_text: str) -> list[str]:
        paragraphs: list[str] = []
        current: list[str] = []

        def flush() -> None:
            if not current:
                return
            paragraphs.append(" ".join(current).strip())
            current.clear()

        for raw_line in raw_text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                flush()
                continue
            if self._is_noise_line(line):
                continue
            if self._looks_like_heading(line) or self._looks_like_bullet(line):
                flush()
                paragraphs.append(line)
                continue
            if not current:
                current.append(line)
                continue
            if self._should_merge_line(current[-1], line):
                current.append(line)
            else:
                flush()
                current.append(line)

        flush()
        return paragraphs

    def _extract_sections(self, paragraphs: list[str]) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for paragraph in paragraphs:
            match = SECTION_HEADING_PATTERN.match(paragraph)
            if match:
                if current is not None:
                    sections.append(current)
                current = {"title": self._clean_heading(match.group("title")), "body": []}
                continue
            if current is not None:
                current["body"].append(paragraph)

        if current is not None:
            sections.append(current)
        return sections

    def _select_problem_title(self, paragraphs: list[str]) -> str:
        for paragraph in paragraphs[:8]:
            candidate = self._clean_heading(paragraph)
            if self._is_generic_title(candidate):
                continue
            if len(candidate) < 10:
                continue
            return self._truncate_text(candidate, max_chars=255)
        return "Problem statement"

    def _select_problem_content(
        self,
        *,
        raw_text: str,
        paragraphs: list[str],
        sections: list[dict[str, Any]],
    ) -> str:
        summary_parts: list[str] = []
        for paragraph in paragraphs[:8]:
            lowered = paragraph.lower()
            if "inti rekomendasi" in lowered or "executive summary" in lowered:
                summary_parts.append(paragraph)
        for section in sections:
            if self._is_problem_section_title(section["title"]):
                summary_parts.extend(section["body"][:2])
                break
        if not summary_parts:
            summary_parts = paragraphs[:3]
        return self._join_excerpt(summary_parts, max_chars=1600) or self._truncate_text(raw_text, max_chars=1600)

    def _extract_branch_candidates(
        self,
        *,
        paragraphs: list[str],
        sections: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        seen: set[str] = set()

        def add_candidate(*, title: str, content: str, context: str | None = None) -> None:
            normalized_content = self._truncate_text(content, max_chars=1000)
            normalized_title = self._compact_title(title or content, fallback="Sub-problem")
            if not normalized_content:
                return
            key = f"{normalized_title.lower()}::{normalized_content[:120].lower()}"
            if key in seen:
                return
            seen.add(key)
            candidates.append(
                {
                    "title": normalized_title,
                    "content": normalized_content,
                    "context": self._truncate_text(context or normalized_title, max_chars=255),
                }
            )

        problem_section = next(
            (section for section in sections if self._is_problem_section_title(section["title"])),
            None,
        )
        if problem_section is not None:
            for bullet in self._extract_bullets(problem_section["body"]):
                add_candidate(
                    title=bullet,
                    content=bullet,
                    context=problem_section["title"],
                )

        for section in sections:
            if len(candidates) >= 4:
                break
            if problem_section is not None and section["title"] == problem_section["title"]:
                continue
            body_excerpt = self._join_excerpt(section["body"], max_chars=900)
            if not body_excerpt:
                continue
            add_candidate(
                title=section["title"],
                content=body_excerpt,
                context=section["title"],
            )

        if not candidates:
            for bullet in self._extract_bullets(paragraphs):
                add_candidate(title=bullet, content=bullet)
                if len(candidates) >= 4:
                    break

        if not candidates:
            for chunk in self._chunk_paragraphs(paragraphs):
                add_candidate(title=chunk, content=chunk)
                if len(candidates) >= 3:
                    break

        return candidates[:4]

    def _build_stub_branch(
        self,
        *,
        root_id: UUID,
        created_at,
        branch_index: int,
        branch: dict[str, str],
    ) -> tuple[list[GraphNode], list[dict[str, Any]]]:
        base_y = branch_index * 220
        label = self._compact_title(branch["title"], fallback=f"Sub-problem {branch_index + 1}")
        branch_content = branch["content"]
        context = branch.get("context") or label
        hypothesis_content, analysis_content, synthesis_content = self._build_branch_narrative(
            label=label,
            content=branch_content,
            context=context,
        )
        evidence_content = self._join_excerpt([context, branch_content], max_chars=1000)

        nodes = [
            GraphNode(
                id=uuid4(),
                rank=NodeRank.SUB_PROBLEM,
                title=self._truncate_text(label, max_chars=255),
                content=self._truncate_text(branch_content, max_chars=1000),
                source=NodeSource.INGEST,
                position=Position(x=320, y=base_y),
                metadata={"generator": "deterministic_stub"},
                created_at=created_at,
                updated_at=created_at,
            ),
            GraphNode(
                id=uuid4(),
                rank=NodeRank.HYPOTHESIS,
                title=self._truncate_text(f"Hypothesis: {label}", max_chars=255),
                content=self._truncate_text(hypothesis_content, max_chars=1000),
                source=NodeSource.INGEST,
                position=Position(x=640, y=base_y),
                metadata={"generator": "deterministic_stub"},
                created_at=created_at,
                updated_at=created_at,
            ),
            GraphNode(
                id=uuid4(),
                rank=NodeRank.FRAMEWORK_ANALYSIS,
                title=self._truncate_text(f"Analysis: {label}", max_chars=255),
                content=self._truncate_text(analysis_content, max_chars=1000),
                source=NodeSource.INGEST,
                position=Position(x=960, y=base_y),
                metadata={"generator": "deterministic_stub"},
                created_at=created_at,
                updated_at=created_at,
            ),
            GraphNode(
                id=uuid4(),
                rank=NodeRank.SUPPORTING_DATA,
                title=self._truncate_text(f"Evidence: {label}", max_chars=255),
                content=self._truncate_text(evidence_content, max_chars=1000),
                source=NodeSource.INGEST,
                position=Position(x=1280, y=base_y),
                metadata={"generator": "deterministic_stub"},
                created_at=created_at,
                updated_at=created_at,
            ),
            GraphNode(
                id=uuid4(),
                rank=NodeRank.SYNTHESIS,
                title=self._truncate_text(f"Synthesis: {label}", max_chars=255),
                content=self._truncate_text(synthesis_content, max_chars=1000),
                source=NodeSource.INGEST,
                position=Position(x=1600, y=base_y),
                metadata={"generator": "deterministic_stub"},
                created_at=created_at,
                updated_at=created_at,
            ),
        ]

        ordered_ids = [root_id, *[node.id for node in nodes]]
        edges = [
            {
                "id": str(uuid4()),
                "source": str(source_id),
                "target": str(target_id),
                "label": None,
                "metadata": {},
                "created_at": created_at.isoformat(),
                "updated_at": created_at.isoformat(),
            }
            for source_id, target_id in zip(ordered_ids, ordered_ids[1:], strict=False)
        ]
        return nodes, edges

    def _build_branch_narrative(self, *, label: str, content: str, context: str) -> tuple[str, str, str]:
        lowered = f"{label} {content} {context}".lower()
        if any(keyword in lowered for keyword in ("stock", "inventory", "stok", "reorder", "warehouse")):
            return (
                "Inventory performance is deteriorating because stock visibility and replenishment controls are weak.",
                "Measure stockout frequency, reorder point coverage, supplier lead times, and fast-moving SKU exposure.",
                "Prioritize inventory digitization and automated replenishment controls on the highest-risk items.",
            )
        if any(keyword in lowered for keyword in ("approval", "procurement", "pembelian", "vendor", "purchase")):
            return (
                "Manual approval routing is slowing procurement and forcing reactive purchasing decisions.",
                "Map request-to-approval cycle time, approval handoffs, exception handling, and procurement bottlenecks.",
                "Digitize procurement workflow and approval routing to reduce delay and improve purchasing discipline.",
            )
        if any(keyword in lowered for keyword in ("data", "rekonsiliasi", "reconciliation", "visibilitas", "visibility")):
            return (
                "Decision quality is constrained by fragmented data and too much manual reconciliation work.",
                "Assess source-system consistency, data latency, reconciliation effort, and reporting ownership.",
                "Create a single operational data layer before scaling broader workflow automation.",
            )
        if any(keyword in lowered for keyword in ("investasi", "investment", "payback", "cost", "roi")):
            return (
                "The business case depends on whether the initiative can convert cost and timing improvements into financial return.",
                "Test implementation cost, expected savings, payback timing, and adoption assumptions against downside cases.",
                "Proceed only with a phased rollout that protects payback economics and implementation control.",
            )
        return (
            f"{label} appears to be a material driver of the broader problem and should be tested as a causal hypothesis.",
            f"Analyze the process gaps, constraints, and measurable signals linked to {label.lower()}.",
            f"Use the evidence on {label.lower()} to decide whether the branch supports a stronger implementation case.",
        )

    def _extract_bullets(self, paragraphs: list[str]) -> list[str]:
        bullets: list[str] = []
        for paragraph in paragraphs:
            match = BULLET_PATTERN.match(paragraph)
            if match is None:
                continue
            bullets.append(self._clean_heading(match.group("content")))
        return bullets

    def _chunk_paragraphs(self, paragraphs: list[str], *, chunk_size: int = 2) -> list[str]:
        chunks: list[str] = []
        clean_paragraphs = [paragraph for paragraph in paragraphs if not self._looks_like_heading(paragraph)]
        for index in range(0, len(clean_paragraphs), chunk_size):
            chunk = self._join_excerpt(clean_paragraphs[index : index + chunk_size], max_chars=900)
            if chunk:
                chunks.append(chunk)
        return chunks

    def _looks_like_heading(self, line: str) -> bool:
        if SECTION_HEADING_PATTERN.match(line):
            return True
        if len(line) > 80:
            return False
        words = line.split()
        if len(words) > 10:
            return False
        letters_only = re.sub(r"[^A-Za-z]", "", line)
        return bool(letters_only) and line == line.upper()

    def _looks_like_bullet(self, line: str) -> bool:
        return BULLET_PATTERN.match(line) is not None

    def _should_merge_line(self, previous: str, current: str) -> bool:
        if previous.endswith((".", "!", "?", ":")):
            return False
        if self._looks_like_heading(current) or self._looks_like_bullet(current):
            return False
        return True

    def _is_noise_line(self, line: str) -> bool:
        lowered = line.lower()
        return (
            lowered.startswith("dokumen internal")
            or lowered.startswith("internal document")
            or bool(re.fullmatch(r"halaman \d+", lowered))
            or bool(re.fullmatch(r"page \d+", lowered))
        )

    def _clean_heading(self, value: str) -> str:
        cleaned = SECTION_HEADING_PATTERN.sub(lambda match: match.group("title"), value, count=1)
        cleaned = BULLET_PATTERN.sub(lambda match: match.group("content"), cleaned, count=1)
        return re.sub(r"\s+", " ", cleaned).strip(" -")

    def _compact_title(self, value: str, *, fallback: str, max_words: int = 8, max_chars: int = 72) -> str:
        cleaned = self._clean_heading(value)
        if not cleaned:
            return fallback
        first_clause = re.split(r"[;:.]", cleaned, maxsplit=1)[0].strip()
        words = first_clause.split()
        candidate = " ".join(words[:max_words]) if words else fallback
        return self._truncate_text(candidate or fallback, max_chars=max_chars)

    def _join_excerpt(self, values: list[str], *, max_chars: int) -> str:
        excerpt_parts: list[str] = []
        for value in values:
            cleaned = self._clean_heading(value)
            if not cleaned:
                continue
            if cleaned in excerpt_parts:
                continue
            excerpt_parts.append(cleaned)
        return self._truncate_text("\n\n".join(excerpt_parts), max_chars=max_chars)

    def _truncate_text(self, value: str | None, *, max_chars: int) -> str:
        if not value:
            return ""
        cleaned = re.sub(r"\s+\n", "\n", value).strip()
        if len(cleaned) <= max_chars:
            return cleaned
        truncated = cleaned[: max_chars - 1].rsplit(" ", 1)[0].strip()
        return f"{truncated or cleaned[: max_chars - 1]}..."

    def _is_generic_title(self, value: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
        return normalized in {
            "",
            "business case",
            "dokumen internal",
            "internal document",
        }

    def _is_problem_section_title(self, value: str) -> bool:
        lowered = value.lower()
        return any(
            keyword in lowered
            for keyword in (
                "latar belakang",
                "masalah",
                "problem",
                "pain point",
                "issue",
                "challenge",
            )
        )

    def _graph_from_ingest_payload(
        self,
        *,
        project_id: UUID,
        workspace_id: UUID,
        workspace_version: int,
        payload: dict[str, Any],
        provider_name: str,
    ) -> WorkspaceGraph:
        created_at = self._now()
        node_lookup: dict[str, UUID] = {}
        nodes: list[dict[str, Any]] = []
        for index, item in enumerate(payload.get("nodes", [])):
            key = str(item.get("key") or f"node-{index}")
            node_id = uuid4()
            node_lookup[key] = node_id
            nodes.append(
                {
                    "id": str(node_id),
                    "rank": int(item.get("rank", index + 1)),
                    "title": item.get("title") or key,
                    "content": item.get("content"),
                    "source": item.get("source") or NodeSource.INGEST.value,
                    "position": item.get("position") or {"x": index * 320, "y": 0},
                    "metadata": item.get("metadata") or {},
                    "created_at": created_at.isoformat(),
                    "updated_at": created_at.isoformat(),
                }
            )

        edges: list[dict[str, Any]] = []
        for item in payload.get("edges", []):
            source_key = str(item.get("source_key"))
            target_key = str(item.get("target_key"))
            if source_key not in node_lookup or target_key not in node_lookup:
                continue
            edges.append(
                {
                    "id": str(uuid4()),
                    "source": str(node_lookup[source_key]),
                    "target": str(node_lookup[target_key]),
                    "label": item.get("label"),
                    "metadata": item.get("metadata") or {},
                    "created_at": created_at.isoformat(),
                    "updated_at": created_at.isoformat(),
                }
            )

        return WorkspaceGraph.model_validate(
            {
                "nodes": nodes,
                "edges": edges,
                "metadata": {
                    "project_id": str(project_id),
                    "workspace_id": str(workspace_id),
                    "version": workspace_version,
                    "updated_at": created_at.isoformat(),
                    "validation": GraphValidationSummary(is_valid=True).model_dump(mode="json"),
                    "attributes": {"ingest_mode": provider_name},
                },
            }
        )

    def _build_stub_mutation_patch(self, *, graph: WorkspaceGraph, instruction: str) -> list[PatchCommand]:
        if not graph.nodes:
            return [
                AddNodeCommand(
                    type="add_node",
                    node=NodeDraft(
                        rank=NodeRank.PROBLEM_STATEMENT,
                        title=instruction[:255] or "New problem statement",
                        content=instruction or "Created by deterministic stub patch.",
                        source=NodeSource.AI,
                        position=Position(x=0, y=0),
                    ),
                )
            ]

        sorted_nodes = sorted(graph.nodes, key=lambda node: (int(node.rank), node.title.lower(), str(node.id)))
        deepest = sorted_nodes[-1]
        if deepest.rank == NodeRank.SYNTHESIS:
            return [
                UpdateNodeCommand(
                    type="update_node",
                    node_id=deepest.id,
                    content=instruction[:1000] or deepest.content,
                    source=NodeSource.AI,
                )
            ]

        next_rank = NodeRank(int(deepest.rank) + 1)
        new_node_id = uuid4()
        add_node = AddNodeCommand(
            type="add_node",
            node=NodeDraft(
                id=new_node_id,
                rank=next_rank,
                title=f"{next_rank.kind.replace('_', ' ').title()}",
                content=instruction[:1000] or "Generated by deterministic stub patch.",
                source=NodeSource.AI,
                position=Position(x=deepest.position.x + 320, y=deepest.position.y),
                metadata={},
            ),
        )
        add_edge = AddEdgeCommand(
            type="add_edge",
            edge={
                "id": uuid4(),
                "source": deepest.id,
                "target": new_node_id,
                "label": None,
                "metadata": {},
            },
        )
        return [add_node, add_edge]

    def build_graph_change_actions(
        self,
        *,
        current_graph: WorkspaceGraph,
        rewritten_graph: WorkspaceGraph,
    ) -> list[str]:
        current_nodes = {node.id: node for node in current_graph.nodes}
        rewritten_nodes = {node.id: node for node in rewritten_graph.nodes}
        current_node_ids = set(current_nodes)
        rewritten_node_ids = set(rewritten_nodes)

        actions: list[str] = []
        actions.extend(["delete_node"] * len(current_node_ids - rewritten_node_ids))
        actions.extend(["add_node"] * len(rewritten_node_ids - current_node_ids))

        for node_id in current_node_ids & rewritten_node_ids:
            if self._node_has_changed(current_nodes[node_id], rewritten_nodes[node_id]):
                actions.append("update_node")

        current_edges = {self._edge_signature(edge) for edge in current_graph.edges}
        rewritten_edges = {self._edge_signature(edge) for edge in rewritten_graph.edges}
        actions.extend(["delete_edge"] * len(current_edges - rewritten_edges))
        actions.extend(["add_edge"] * len(rewritten_edges - current_edges))
        return actions

    def _build_stub_workspace_chat_response(
        self,
        *,
        graph: WorkspaceGraph,
        instruction: str,
        focus_node_id: UUID | None = None,
    ) -> tuple[str, WorkspaceGraph | None]:
        framework = self._detect_framework_request(instruction)
        if framework is not None:
            if self._looks_like_framework_graph_request(instruction):
                return "rewrite_graph", self._apply_framework_to_graph(
                    graph=graph,
                    framework=framework,
                    focus_node_id=focus_node_id,
                )
            return "explain", None

        if self._looks_like_explanation_request(instruction):
            return "explain", None

        target_rank = self._extract_requested_rank(instruction)
        if target_rank is not None and self._looks_like_delete_request(instruction):
            removed_node_ids = {
                node.id
                for node in graph.nodes
                if int(node.rank) == target_rank
            }
            if removed_node_ids:
                parent_lookup: dict[UUID, set[UUID]] = defaultdict(set)
                for edge in graph.edges:
                    parent_lookup[edge.target].add(edge.source)

                changed = True
                while changed:
                    changed = False
                    for node in graph.nodes:
                        if node.id in removed_node_ids or node.rank == NodeRank.PROBLEM_STATEMENT:
                            continue
                        surviving_parents = {
                            parent_id
                            for parent_id in parent_lookup.get(node.id, set())
                            if parent_id not in removed_node_ids
                        }
                        if not surviving_parents:
                            removed_node_ids.add(node.id)
                            changed = True

                rewritten_nodes = [
                    node.model_copy(deep=True)
                    for node in graph.nodes
                    if node.id not in removed_node_ids
                ]
                rewritten_edges = [
                    edge.model_copy(deep=True)
                    for edge in graph.edges
                    if edge.source not in removed_node_ids and edge.target not in removed_node_ids
                ]
                rewritten_graph = self._build_workspace_graph(
                    current_graph=graph,
                    nodes=rewritten_nodes,
                    edges=rewritten_edges,
                )
                ensure_valid_graph(rewritten_graph)
                return "rewrite_graph", rewritten_graph

        commands = self._build_stub_mutation_patch(graph=graph, instruction=instruction)
        rewritten_graph, _, _ = apply_mutation_commands(graph, list(commands))
        ensure_valid_graph(rewritten_graph)
        return "rewrite_graph", rewritten_graph

    def _graph_from_workspace_rewrite_payload(
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
            raise AIProviderError("Workspace chat graph payload must include nodes and edges arrays.")

        existing_nodes_by_id = {node.id: node for node in current_graph.nodes}
        existing_node_tokens = {str(node.id): node for node in current_graph.nodes}
        existing_edges_by_pair = {(edge.source, edge.target): edge for edge in current_graph.edges}
        existing_edge_tokens = {str(edge.id): edge for edge in current_graph.edges}

        now = self._now()
        rank_counts: dict[int, int] = defaultdict(int)
        node_aliases: dict[str, UUID] = {}
        normalized_nodes: list[GraphNode] = []
        normalized_node_ids: set[UUID] = set()

        for index, item in enumerate(raw_nodes):
            if not isinstance(item, dict):
                continue

            raw_id = str(item.get("id") or f"generated-node-{index}")
            node_id = self._resolve_rewrite_id(
                raw_id,
                aliases=node_aliases,
                existing_lookup=existing_node_tokens,
            )
            normalized_node_ids.add(node_id)
            existing_node = existing_nodes_by_id.get(node_id)

            rank_value = item.get("rank", existing_node.rank if existing_node else None)
            if rank_value is None:
                raise AIProviderError("Workspace chat graph payload omitted node rank.")
            rank = NodeRank(int(rank_value))

            title = str(item.get("title") or (existing_node.title if existing_node else "")).strip()
            if not title:
                raise AIProviderError("Workspace chat graph payload omitted node title.")

            raw_position = item.get("position") if isinstance(item.get("position"), dict) else None
            lane_index = rank_counts[int(rank)]
            rank_counts[int(rank)] += 1
            default_position = Position(x=lane_index * 320, y=(int(rank) - 1) * 220)
            if raw_position is not None:
                position = Position(
                    x=float(raw_position.get("x", default_position.x)),
                    y=float(raw_position.get("y", default_position.y)),
                )
            elif existing_node is not None:
                position = existing_node.position
            else:
                position = default_position

            source_value = item.get("source") or (
                existing_node.source.value if existing_node is not None else NodeSource.AI.value
            )
            metadata = (
                dict(item.get("metadata"))
                if isinstance(item.get("metadata"), dict)
                else dict(existing_node.metadata) if existing_node is not None else {}
            )
            content = item.get("content") if "content" in item else (
                existing_node.content if existing_node is not None else None
            )

            normalized_nodes.append(
                GraphNode(
                    id=node_id,
                    rank=rank,
                    title=title,
                    content=str(content) if isinstance(content, (int, float)) else content,
                    source=NodeSource(str(source_value)),
                    position=position,
                    metadata=metadata,
                    created_at=existing_node.created_at if existing_node is not None else now,
                    updated_at=now,
                )
            )

        normalized_node_lookup = {node.id: node for node in normalized_nodes}
        normalized_edges: list[GraphEdge] = []

        for index, item in enumerate(raw_edges):
            if not isinstance(item, dict):
                continue
            source_id = self._resolve_node_reference(
                item.get("source"),
                aliases=node_aliases,
                allowed_node_ids=set(normalized_node_lookup),
            )
            target_id = self._resolve_node_reference(
                item.get("target"),
                aliases=node_aliases,
                allowed_node_ids=set(normalized_node_lookup),
            )
            existing_edge = existing_edges_by_pair.get((source_id, target_id))
            raw_edge_id = item.get("id")
            if raw_edge_id is None and existing_edge is not None:
                edge_id = existing_edge.id
            else:
                edge_id = self._resolve_rewrite_id(
                    str(raw_edge_id or f"generated-edge-{index}"),
                    aliases={},
                    existing_lookup=existing_edge_tokens,
                )
            metadata = (
                dict(item.get("metadata"))
                if isinstance(item.get("metadata"), dict)
                else dict(existing_edge.metadata) if existing_edge is not None else {}
            )
            normalized_edges.append(
                GraphEdge(
                    id=edge_id,
                    source=source_id,
                    target=target_id,
                    label=item.get("label") if "label" in item else (
                        existing_edge.label if existing_edge is not None else None
                    ),
                    metadata=metadata,
                    created_at=existing_edge.created_at if existing_edge is not None else now,
                    updated_at=now,
                )
            )

        return self._build_workspace_graph(
            current_graph=current_graph,
            nodes=normalized_nodes,
            edges=normalized_edges,
        )

    def _build_workspace_graph(
        self,
        *,
        current_graph: WorkspaceGraph,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> WorkspaceGraph:
        return WorkspaceGraph(
            nodes=nodes,
            edges=edges,
            metadata=GraphMetadata(
                project_id=current_graph.metadata.project_id,
                workspace_id=current_graph.metadata.workspace_id,
                version=current_graph.metadata.version,
                updated_at=self._now(),
                validation=GraphValidationSummary(is_valid=True),
                attributes=dict(current_graph.metadata.attributes),
            ),
        )

    def _resolve_rewrite_id(
        self,
        token: str,
        *,
        aliases: dict[str, UUID],
        existing_lookup: dict[str, Any],
    ) -> UUID:
        if token in aliases:
            return aliases[token]
        if token in existing_lookup:
            resolved = UUID(token)
        else:
            try:
                resolved = UUID(token)
            except (TypeError, ValueError):
                resolved = uuid4()
        aliases[token] = resolved
        return resolved

    def _resolve_node_reference(
        self,
        raw_reference: Any,
        *,
        aliases: dict[str, UUID],
        allowed_node_ids: set[UUID],
    ) -> UUID:
        token = str(raw_reference or "").strip()
        if not token:
            raise AIProviderError("Workspace chat graph edge is missing a node reference.")
        node_id = aliases.get(token)
        if node_id is None:
            try:
                node_id = UUID(token)
            except (TypeError, ValueError) as exc:
                raise AIProviderError("Workspace chat graph edge referenced an unknown node id.", details=token) from exc
        if node_id not in allowed_node_ids:
            raise AIProviderError("Workspace chat graph edge referenced a node that is not present in nodes.")
        return node_id

    def _coerce_workspace_chat_action(self, raw_action: Any, *, instruction: str) -> str:
        if raw_action in {"explain", "rewrite_graph"}:
            return str(raw_action)
        return "explain" if self._looks_like_explanation_request(instruction) else "rewrite_graph"

    def _coerce_workspace_chat_summary(
        self,
        raw_summary: Any,
        *,
        action: str,
        instruction: str,
        current_graph: WorkspaceGraph,
        rewritten_graph: WorkspaceGraph | None,
        focus_node_id: UUID | None = None,
    ) -> str:
        if isinstance(raw_summary, str) and raw_summary.strip():
            return self._truncate_text(raw_summary.strip(), max_chars=1200)
        if action == "explain":
            return self._build_explanation_response(
                instruction=instruction,
                graph=current_graph,
                focus_node_id=focus_node_id,
            )
        return self._build_workspace_chat_rewrite_summary(
            instruction=instruction,
            current_graph=current_graph,
            rewritten_graph=rewritten_graph or current_graph,
        )

    def _extract_workspace_chat_summary(self, payload: dict[str, Any]) -> str | None:
        for key in ("summary", "answer", "response", "explanation", "message", "assistant_response"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _build_workspace_chat_rewrite_summary(
        self,
        *,
        instruction: str,
        current_graph: WorkspaceGraph,
        rewritten_graph: WorkspaceGraph,
    ) -> str:
        actions = self.build_graph_change_actions(
            current_graph=current_graph,
            rewritten_graph=rewritten_graph,
        )
        if not actions:
            return self._truncate_text(
                f"Tidak ada perubahan graph yang diperlukan. Permintaan: {instruction.strip()}",
                max_chars=1200,
            )
        type_counts: dict[str, int] = defaultdict(int)
        for action in actions:
            type_counts[action] += 1
        action_parts = [
            f"{count} {action.replace('_', ' ')}"
            for action, count in sorted(type_counts.items())
        ]
        return self._truncate_text(
            f"Graph diperbarui sesuai permintaan. Applied {', '.join(action_parts)}. Request: {instruction.strip()}",
            max_chars=1200,
        )

    def _build_explanation_response(
        self,
        *,
        instruction: str,
        graph: WorkspaceGraph,
        focus_node_id: UUID | None = None,
    ) -> str:
        framework = self._detect_framework_request(instruction)
        if framework is not None:
            return self._build_framework_response(
                framework=framework,
                graph=graph,
                instruction=instruction,
                focus_node_id=focus_node_id,
                graph_changed=False,
            )

        counts_by_rank: dict[int, int] = defaultdict(int)
        for node in graph.nodes:
            counts_by_rank[int(node.rank)] += 1

        target_rank = self._extract_requested_rank(instruction)
        if target_rank is not None:
            kind = NodeRank(target_rank).kind.replace("_", " ")
            nodes_in_rank = [node.title for node in graph.nodes if int(node.rank) == target_rank][:3]
            title_suffix = (
                f" Node yang ada di rank ini: {', '.join(nodes_in_rank)}."
                if nodes_in_rank
                else " Saat ini tidak ada node di rank tersebut."
            )
            return self._truncate_text(
                f"Rank {target_rank} berfungsi sebagai {kind} dan saat ini memiliki {counts_by_rank.get(target_rank, 0)} node di workspace ini.{title_suffix} Graph tidak diubah.",
                max_chars=1200,
            )

        root = next((node for node in graph.nodes if int(node.rank) == 1), None)
        sub_problem_titles = [node.title for node in graph.nodes if int(node.rank) == 2][:3]
        hypothesis_titles = [node.title for node in graph.nodes if int(node.rank) == 3][:3]
        synthesis_points = [
            self._truncate_text(node.content or node.title, max_chars=120)
            for node in graph.nodes
            if int(node.rank) == 6
        ][:2]

        explanation_parts: list[str] = []
        if root is not None:
            explanation_parts.append(
                f"Case ini berpusat pada masalah utama: {root.title}. {self._truncate_text(root.content or '', max_chars=180)}"
            )
        if sub_problem_titles:
            explanation_parts.append(
                f"Sub-problem utamanya: {', '.join(sub_problem_titles)}."
            )
        if hypothesis_titles:
            explanation_parts.append(
                f"Hipotesis yang sedang diuji: {', '.join(hypothesis_titles)}."
            )
        if synthesis_points:
            explanation_parts.append(
                f"Arah rekomendasi saat ini: {' '.join(synthesis_points)}"
            )
        explanation_parts.append("Graph tidak diubah.")

        return self._truncate_text(
            " ".join(part for part in explanation_parts if part).strip(),
            max_chars=1200,
        )

    def _extract_requested_rank(self, instruction: str) -> int | None:
        match = re.search(r"rank\s*(\d)", instruction.lower())
        if match is None:
            return None
        rank_value = int(match.group(1))
        return rank_value if 1 <= rank_value <= 6 else None

    def _looks_like_delete_request(self, instruction: str) -> bool:
        lowered = instruction.lower()
        return any(keyword in lowered for keyword in ("hapus", "delete", "remove", "drop"))

    def _looks_like_explanation_request(self, instruction: str) -> bool:
        lowered = instruction.lower()
        if self._detect_framework_request(instruction) is not None and not self._looks_like_framework_graph_request(instruction):
            return True
        if any(
            keyword in lowered
            for keyword in (
                "hapus",
                "delete",
                "remove",
                "tambah",
                "add",
                "buat",
                "create",
                "ubah",
                "update",
                "ganti",
                "move",
                "geser",
                "pecah",
                "split",
                "merge",
                "hubungkan",
                "disconnect",
                "rewrite",
                "edit",
                "rapikan",
            )
        ):
            return False
        return "?" in instruction or any(
            keyword in lowered
            for keyword in (
                "jelaskan",
                "explain",
                "apa",
                "kenapa",
                "mengapa",
                "why",
                "how",
                "bagaimana",
                "deskripsikan",
                "describe",
                "ringkas",
                "summary",
                "summarize",
            )
        )

    def _looks_like_framework_graph_request(self, instruction: str) -> bool:
        lowered = instruction.lower()
        return any(
            keyword in lowered
            for keyword in (
                "graph",
                "canvas",
                "node",
                "rank 4",
                "workspace",
                "framework node",
                "masukkan ke graph",
                "masukin ke graph",
                "tambahkan ke graph",
                "apply ke graph",
            )
        )

    def _detect_framework_request(self, instruction: str) -> dict[str, Any] | None:
        lowered = instruction.lower()
        for framework in STRATEGY_FRAMEWORKS:
            if any(alias in lowered for alias in framework["aliases"]):
                return framework
        return None

    def _find_node_by_id(self, graph: WorkspaceGraph, node_id: UUID | None) -> GraphNode | None:
        if node_id is None:
            return None
        return next((node for node in graph.nodes if node.id == node_id), None)

    def _walk_to_rank(
        self,
        *,
        graph: WorkspaceGraph,
        start_node: GraphNode,
        target_rank: NodeRank,
        direction: str,
    ) -> GraphNode | None:
        adjacency: dict[UUID, list[UUID]] = defaultdict(list)
        for edge in graph.edges:
            if direction == "incoming":
                adjacency[edge.target].append(edge.source)
            else:
                adjacency[edge.source].append(edge.target)

        visited: set[UUID] = {start_node.id}
        queue: list[UUID] = list(adjacency.get(start_node.id, []))

        while queue:
            candidate_id = queue.pop(0)
            if candidate_id in visited:
                continue
            visited.add(candidate_id)
            candidate = self._find_node_by_id(graph, candidate_id)
            if candidate is None:
                continue
            if candidate.rank == target_rank:
                return candidate
            queue.extend(adjacency.get(candidate.id, []))

        return None

    def _resolve_framework_anchor(self, graph: WorkspaceGraph, focus_node_id: UUID | None) -> GraphNode | None:
        focus_node = self._find_node_by_id(graph, focus_node_id)
        if focus_node is not None:
            if focus_node.rank == NodeRank.HYPOTHESIS:
                return focus_node
            if int(focus_node.rank) < int(NodeRank.HYPOTHESIS):
                connected = self._walk_to_rank(
                    graph=graph,
                    start_node=focus_node,
                    target_rank=NodeRank.HYPOTHESIS,
                    direction="outgoing",
                )
                if connected is not None:
                    return connected
            else:
                connected = self._walk_to_rank(
                    graph=graph,
                    start_node=focus_node,
                    target_rank=NodeRank.HYPOTHESIS,
                    direction="incoming",
                )
                if connected is not None:
                    return connected

        return next((node for node in graph.nodes if node.rank == NodeRank.HYPOTHESIS), None)

    def _resolve_existing_framework_node(
        self,
        *,
        graph: WorkspaceGraph,
        anchor_node: GraphNode,
        focus_node_id: UUID | None,
    ) -> GraphNode | None:
        focus_node = self._find_node_by_id(graph, focus_node_id)
        if focus_node is not None and focus_node.rank == NodeRank.FRAMEWORK_ANALYSIS:
            return focus_node

        outgoing = [edge.target for edge in graph.edges if edge.source == anchor_node.id]
        for node_id in outgoing:
            node = self._find_node_by_id(graph, node_id)
            if node is not None and node.rank == NodeRank.FRAMEWORK_ANALYSIS:
                return node
        return None

    def _build_framework_content(self, *, framework: dict[str, Any], anchor_node: GraphNode) -> str:
        return "\n".join(
            [
                f"Recommended framework: {framework['title']}",
                "",
                f"Branch anchor: {anchor_node.title}",
                "Use this lens to structure the analysis before moving to evidence.",
                "",
                "Key prompts:",
                *[f"- {label}" for label in framework["prompt_labels"]],
            ]
        )

    def _apply_framework_to_graph(
        self,
        *,
        graph: WorkspaceGraph,
        framework: dict[str, Any],
        focus_node_id: UUID | None,
    ) -> WorkspaceGraph:
        anchor_node = self._resolve_framework_anchor(graph, focus_node_id)
        if anchor_node is None:
            return graph

        existing_framework = self._resolve_existing_framework_node(
            graph=graph,
            anchor_node=anchor_node,
            focus_node_id=focus_node_id,
        )
        now = self._now()
        nodes = [node.model_copy(deep=True) for node in graph.nodes]
        edges = [edge.model_copy(deep=True) for edge in graph.edges]

        if existing_framework is not None:
            for index, node in enumerate(nodes):
                if node.id == existing_framework.id:
                    nodes[index] = node.model_copy(
                        update={
                            "title": framework["title"],
                            "content": self._build_framework_content(
                                framework=framework,
                                anchor_node=anchor_node,
                            ),
                            "source": NodeSource.AI,
                            "updated_at": now,
                            "metadata": {
                                **dict(node.metadata),
                                "framework_key": framework["id"],
                                "recommended_for": str(anchor_node.id),
                            },
                        }
                    )
                    break
        else:
            new_node = GraphNode(
                id=uuid4(),
                rank=NodeRank.FRAMEWORK_ANALYSIS,
                title=framework["title"],
                content=self._build_framework_content(framework=framework, anchor_node=anchor_node),
                source=NodeSource.AI,
                position=Position(x=anchor_node.position.x + 320, y=anchor_node.position.y),
                metadata={
                    "branch_index": anchor_node.metadata.get("branch_index", 0),
                    "framework_key": framework["id"],
                    "recommended_for": str(anchor_node.id),
                },
                created_at=now,
                updated_at=now,
            )
            nodes.append(new_node)
            edges.append(
                GraphEdge(
                    id=uuid4(),
                    source=anchor_node.id,
                    target=new_node.id,
                    label=None,
                    metadata={},
                    created_at=now,
                    updated_at=now,
                )
            )

        return self._build_workspace_graph(current_graph=graph, nodes=nodes, edges=edges)

    def _build_framework_response(
        self,
        *,
        framework: dict[str, Any],
        graph: WorkspaceGraph,
        instruction: str,
        focus_node_id: UUID | None,
        graph_changed: bool,
    ) -> str:
        anchor_node = self._resolve_framework_anchor(graph, focus_node_id)
        root = next((node for node in graph.nodes if node.rank == NodeRank.PROBLEM_STATEMENT), None)
        evidence_nodes = [node for node in graph.nodes if node.rank == NodeRank.SUPPORTING_DATA][:2]
        synthesis_nodes = [node for node in graph.nodes if node.rank == NodeRank.SYNTHESIS][:2]
        validation_issue = graph.metadata.validation.issues[0].message if graph.metadata.validation.issues else None
        branch_label = anchor_node.title if anchor_node is not None else (root.title if root is not None else "current case")
        evidence_label = ", ".join(node.title for node in evidence_nodes) or "belum ada evidence yang kuat"
        synthesis_label = ", ".join(node.title for node in synthesis_nodes) or "belum ada synthesis final"

        sections: list[str]
        if framework["id"] == "swot":
            sections = [
                f"Strengths: branch sudah punya fokus awal di \"{branch_label}\" dan evidence yang terlihat saat ini adalah {evidence_label}.",
                f"Weaknesses: graph masih punya gap analisis pada {validation_issue or 'pendalaman evidence dan framework pendukung'}.",
                f"Opportunities: case ini bisa diperdalam lewat branch yang paling dekat dengan {branch_label} untuk menghasilkan synthesis yang lebih tajam.",
                f"Threats: tanpa validasi tambahan, rekomendasi bisa bias dan synthesis saat ini masih {synthesis_label}.",
            ]
        elif framework["id"] == "3cs":
            sections = [
                f"Company: kapabilitas internal yang paling relevan saat ini terhubung ke branch \"{branch_label}\".",
                "Competitor: graph saat ini belum punya tekanan kompetitor yang eksplisit, jadi ini harus jadi area evidence tambahan.",
                "Customer: gunakan branch ini untuk menguji apa yang benar-benar dirasakan atau dipilih customer.",
            ]
        elif framework["id"] == "porter":
            sections = [
                "Threat of new entrants: cek seberapa mudah pemain baru meniru atau masuk ke area masalah ini.",
                "Supplier power: nilai apakah ketergantungan upstream memperburuk branch utama.",
                "Buyer power: lihat apakah customer punya daya tawar tinggi terhadap harga atau service.",
                "Threat of substitutes: identifikasi alternatif yang membuat solusi saat ini kurang menarik.",
                "Competitive rivalry: ukur apakah tekanan inti datang dari kompetisi yang terlalu agresif.",
            ]
        elif framework["id"] == "pestel":
            sections = [
                "Political / Legal: cek aturan, kebijakan, atau compliance yang bisa membatasi langkah bisnis.",
                "Economic: ukur dampak biaya, permintaan, atau margin terhadap branch ini.",
                "Social / Technological: nilai perubahan perilaku pengguna dan kesiapan sistem internal.",
                "Environmental: masukkan jika ada implikasi operasi, supply chain, atau governance.",
            ]
        elif framework["id"] == "most":
            sections = [
                f"Mission: pastikan case utama tetap kembali ke problem \"{root.title if root is not None else branch_label}\".",
                "Objectives: turunkan target yang terukur dari mission tadi.",
                "Strategies: pilih beberapa strategic moves yang menjawab branch utama.",
                "Tactics: pastikan tindakan harian benar-benar mendukung strategy, bukan sekadar aktivitas.",
            ]
        elif framework["id"] == "7s":
            sections = [
                "Strategy / Structure: cek apakah arah dan struktur organisasi mendukung branch ini.",
                "Systems / Skills: lihat apakah sistem kerja dan kapabilitas tim cukup matang.",
                "Staff / Style / Shared values: nilai apakah people dan culture memperkuat atau justru menghambat eksekusi.",
            ]
        else:
            sections = [
                f"Primary activities: telusuri aktivitas utama yang mempengaruhi branch \"{branch_label}\".",
                "Support activities: cek sistem, data, procurement, dan capability yang menopang aktivitas utama.",
                f"Value leaks: indikasi kebocoran nilai paling dekat saat ini ada pada {evidence_label}.",
                "Improvement focus: prioritaskan aktivitas dengan impact tertinggi ke cost, speed, atau service.",
            ]

        header = f"{framework['title']} untuk branch \"{branch_label}\"."
        if graph_changed:
            header = f"{header} Framework ini juga sudah saya terapkan ke graph sebagai Rank 4 node."
        else:
            header = f"{header} Graph tidak diubah."
        return self._truncate_text(
            "\n".join([header, "", *[f"- {section}" for section in sections], "", f"Request: {instruction.strip()}"]),
            max_chars=1200,
        )

    @staticmethod
    def _node_has_changed(current_node: GraphNode, rewritten_node: GraphNode) -> bool:
        return any(
            (
                current_node.rank != rewritten_node.rank,
                current_node.title != rewritten_node.title,
                current_node.content != rewritten_node.content,
                current_node.source != rewritten_node.source,
                current_node.position.x != rewritten_node.position.x,
                current_node.position.y != rewritten_node.position.y,
                current_node.metadata != rewritten_node.metadata,
            )
        )

    @staticmethod
    def _edge_signature(edge: GraphEdge) -> tuple[str, str, str | None, str]:
        return (
            str(edge.source),
            str(edge.target),
            edge.label,
            json.dumps(edge.metadata or {}, sort_keys=True),
        )

    def _coerce_summary(
        self,
        raw_summary: Any,
        *,
        instruction: str,
        commands: list[PatchCommand],
    ) -> str:
        if isinstance(raw_summary, str) and raw_summary.strip():
            return self._truncate_text(raw_summary.strip(), max_chars=800)
        return self._build_mutation_summary(instruction=instruction, commands=commands)

    def _build_mutation_summary(self, *, instruction: str, commands: list[PatchCommand]) -> str:
        if not commands:
            return self._truncate_text(
                instruction or "No graph mutation was applied.",
                max_chars=800,
            )

        type_counts: dict[str, int] = {}
        highlighted_titles: list[str] = []
        for command in commands:
            type_counts[str(command.type)] = type_counts.get(str(command.type), 0) + 1
            if isinstance(command, AddNodeCommand):
                highlighted_titles.append(command.node.title)

        action_parts = [
            f"{count} {command_type.replace('_', ' ')}"
            for command_type, count in sorted(type_counts.items())
        ]
        subject = (
            ", ".join(highlighted_titles[:2])
            if highlighted_titles
            else "the workspace graph"
        )
        summary = (
            f"Updated {subject} based on your request. "
            f"Applied {', '.join(action_parts)}."
        )
        if instruction:
            summary = f"{summary} Request: {instruction.strip()}"
        return self._truncate_text(summary, max_chars=800)

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
    def _now():
        from datetime import UTC, datetime

        return datetime.now(UTC)
