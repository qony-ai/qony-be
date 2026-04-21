from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    AIProviderError,
    AppError,
    DomainValidationError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.core.security import Actor
from app.models.export_job import ExportJob
from app.models.project import Project
from app.repositories.projects import ProjectRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository
from app.schemas.export import (
    DeliverableType,
    ExportJobRead,
    SlidePlan,
    SlideStep,
    export_job_to_read,
)
from app.schemas.workspace import GraphNode, WorkspaceGraph
from app.services.ai_router import get_ai_router
from app.services.graph_mapper import workspace_to_graph


SLIDE_PLAN_ADAPTER = TypeAdapter(SlidePlan)

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = WORKSPACE_ROOT / "qony-fe"
EXPORT_COMPONENTS_DIR = FRONTEND_ROOT / "public" / "export-components"
EXPORT_ARTIFACTS_DIR = BACKEND_ROOT / ".artifacts" / "exports"
PLAYWRIGHT_RENDER_SCRIPT = FRONTEND_ROOT / "scripts" / "render-export-pdf.mjs"
MANIFEST_FILENAME = "index.json"

EVIDENCE_NODE_TYPES = {
    "evidence",
    "metric",
    "market_data",
    "trend",
    "competitor",
    "regulation",
}

GENERIC_RECOMMENDATION_POINTS = [
    "Tighten promotion guardrails around margin recovery.",
    "Repair the highest-impact assortment and adjacency gaps.",
    "Track impact with branch-level quality and conversion metrics.",
]


class ExportEngine:
    def __init__(self, *, session: Session, settings: Settings, actor: Actor) -> None:
        self.session = session
        self.settings = settings
        self.actor = actor
        self.user_repository = UserRepository(session)
        self.project_repository = ProjectRepository(session)
        self.workspace_repository = WorkspaceRepository(session)
        self.router = get_ai_router(settings)

    def create_job(
        self,
        *,
        project_id: UUID,
        deliverable_type: DeliverableType,
    ) -> ExportJobRead:
        project, workspace = self._resolve_project_workspace(project_id)
        user = self.user_repository.get_or_create(
            email=self.actor.email,
            name=self.actor.name,
            external_auth_id=self.actor.auth_user_id,
        )
        graph = workspace_to_graph(workspace)
        job = ExportJob(
            project_id=project.id,
            workspace_id=workspace.id,
            requested_by_user_id=user.id,
            deliverable_type=deliverable_type,
            status="pending",
            graph_version_at_request=graph.metadata.version,
            manifest_version=None,
            slide_plan_json={},
            warnings_json=[],
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return export_job_to_read(job)

    def create_and_run_job(
        self,
        *,
        project_id: UUID,
        deliverable_type: DeliverableType,
    ) -> ExportJobRead:
        project, workspace = self._resolve_project_workspace(project_id)
        graph = workspace_to_graph(workspace)
        job = self._create_job_model(
            project=project,
            workspace_id=workspace.id,
            graph=graph,
            deliverable_type=deliverable_type,
        )

        try:
            self._update_job(job, status="planning", error_message=None)
            plan = self.plan_slides(
                project=project,
                graph=graph,
                deliverable_type=deliverable_type,
            )
            self._update_job(
                job,
                manifest_version=plan.manifest_version,
                slide_plan_json=plan.model_dump(mode="json"),
                warnings_json=list(plan.warnings),
            )

            html_artifact_path, pdf_artifact_path = self._build_artifact_paths(job.id)
            rendered_html = self.render_html(plan)
            html_artifact_path.parent.mkdir(parents=True, exist_ok=True)
            html_artifact_path.write_text(rendered_html, encoding="utf-8")

            self._update_job(
                job,
                status="rendering",
                html_artifact_path=str(html_artifact_path),
                pdf_artifact_path=str(pdf_artifact_path),
            )
            self._render_pdf_file(
                html_path=html_artifact_path,
                pdf_path=pdf_artifact_path,
                deliverable_type=deliverable_type,
            )
            self._update_job(
                job,
                status="completed",
                error_message=None,
            )
            return export_job_to_read(job)
        except Exception as exc:
            self._mark_failed(job, exc)
            if isinstance(exc, AppError):
                raise
            raise ServiceUnavailableError(
                "Export generation failed.",
                details=str(exc),
            ) from exc

    def get_job(self, job_id: UUID) -> ExportJobRead:
        job = self._resolve_job(job_id)
        return export_job_to_read(job)

    def get_pdf_artifact(self, job_id: UUID) -> tuple[Path, str]:
        job = self._resolve_job(job_id)
        if job.status != "completed" or not job.pdf_artifact_path:
            raise NotFoundError("Export PDF not found.")
        pdf_path = Path(job.pdf_artifact_path)
        if not pdf_path.exists():
            raise NotFoundError("Export PDF artifact is missing.")
        filename = self._build_pdf_filename(job)
        return pdf_path, filename

    def plan_slides(
        self,
        *,
        project: Project,
        graph: WorkspaceGraph,
        deliverable_type: DeliverableType,
    ) -> SlidePlan:
        manifest, manifest_version = self._load_manifest()
        ai_warning: str | None = None

        if self.router.provider != "stub":
            try:
                plan = self._plan_with_ai(
                    project=project,
                    graph=graph,
                    manifest=manifest,
                    manifest_version=manifest_version,
                    deliverable_type=deliverable_type,
                )
                return plan
            except AppError:
                ai_warning = "AI planner returned invalid output. Used deterministic export planning instead."
            except Exception:
                ai_warning = "AI planner was unavailable. Used deterministic export planning instead."

        plan = self._build_fallback_plan(
            project=project,
            graph=graph,
            deliverable_type=deliverable_type,
            manifest_version=manifest_version,
        )
        if ai_warning:
            plan.warnings.append(ai_warning)
        self._validate_plan_against_manifest(plan, manifest)
        return plan

    def render_html(self, plan: SlidePlan) -> str:
        manifest, _ = self._load_manifest()
        self._validate_plan_against_manifest(plan, manifest)
        components = {
            component["key"]: component
            for component in manifest.get("components") or []
            if isinstance(component, dict) and component.get("key")
        }

        rendered_steps: list[str] = []
        for step in plan.steps:
            component = components.get(step.component_key)
            if component is None:
                raise DomainValidationError(
                    "Slide plan references an unknown component.",
                    details={"component_key": step.component_key},
                )
            template_path = EXPORT_COMPONENTS_DIR / str(component["template"])
            if not template_path.exists():
                raise ServiceUnavailableError(
                    "Export component template is missing.",
                    details={"expected_path": str(template_path)},
                )
            template = template_path.read_text(encoding="utf-8")
            rendered_steps.append(self._render_template(template, step.variables))
        return self._wrap_document(plan, rendered_steps)

    def render_pdf(
        self,
        *,
        html: str,
        deliverable_type: DeliverableType,
    ) -> bytes:
        with TemporaryDirectory(prefix="qony-export-") as temp_dir:
            html_path = Path(temp_dir) / "export.html"
            pdf_path = Path(temp_dir) / "export.pdf"
            html_path.write_text(html, encoding="utf-8")
            self._render_pdf_file(
                html_path=html_path,
                pdf_path=pdf_path,
                deliverable_type=deliverable_type,
            )
            return pdf_path.read_bytes()

    def _create_job_model(
        self,
        *,
        project: Project,
        workspace_id: UUID,
        graph: WorkspaceGraph,
        deliverable_type: DeliverableType,
    ) -> ExportJob:
        user = self.user_repository.get_or_create(
            email=self.actor.email,
            name=self.actor.name,
            external_auth_id=self.actor.auth_user_id,
        )
        job = ExportJob(
            project_id=project.id,
            workspace_id=workspace_id,
            requested_by_user_id=user.id,
            deliverable_type=deliverable_type,
            status="pending",
            graph_version_at_request=graph.metadata.version,
            manifest_version=None,
            slide_plan_json={},
            warnings_json=[],
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def _update_job(self, job: ExportJob, **changes: Any) -> None:
        for key, value in changes.items():
            setattr(job, key, value)
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)

    def _mark_failed(self, job: ExportJob, exc: Exception) -> None:
        self.session.rollback()
        job = self.session.get(ExportJob, job.id)
        if job is None:
            return
        job.status = "failed"
        job.error_message = str(exc)
        self.session.add(job)
        self.session.commit()

    def _resolve_project_workspace(self, project_id: UUID):
        project = self._resolve_project(project_id)
        if project is None:
            raise NotFoundError("Project not found.")
        workspace = self.workspace_repository.get_by_project_id(project.id)
        if workspace is None:
            raise NotFoundError("Workspace not found.")
        return project, workspace

    def _resolve_project(self, project_id: UUID):
        if self.actor.source == "default":
            return self.project_repository.get_by_id(project_id)
        user = self.user_repository.get_or_create(
            email=self.actor.email,
            name=self.actor.name,
            external_auth_id=self.actor.auth_user_id,
        )
        return self.project_repository.get_for_user(project_id, user.id)

    def _resolve_job(self, job_id: UUID) -> ExportJob:
        job = self.session.get(ExportJob, job_id)
        if job is None:
            raise NotFoundError("Export job not found.")
        project = self._resolve_project(job.project_id)
        if project is None:
            raise NotFoundError("Export job not found.")
        return job

    def _load_manifest(self) -> tuple[dict[str, Any], str]:
        manifest_path = EXPORT_COMPONENTS_DIR / MANIFEST_FILENAME
        if not manifest_path.exists():
            raise ServiceUnavailableError(
                "Export component manifest is missing.",
                details={"expected_path": str(manifest_path)},
            )
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
        version = manifest.get("manifest_version") or hashlib.sha256(raw).hexdigest()[:16]
        return manifest, str(version)

    def _plan_with_ai(
        self,
        *,
        project: Project,
        graph: WorkspaceGraph,
        manifest: dict[str, Any],
        manifest_version: str,
        deliverable_type: DeliverableType,
    ) -> SlidePlan:
        system_prompt = self._plan_system_prompt(deliverable_type)
        user_prompt = json.dumps(
            {
                "project": {
                    "id": str(project.id),
                    "name": project.name,
                    "description": project.description,
                },
                "deliverable_type": deliverable_type,
                "manifest_version": manifest_version,
                "manifest": manifest,
                "graph": graph.model_dump(mode="json"),
            }
        )
        try:
            raw = self.router.complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except Exception as exc:
            raise AIProviderError(
                "AI router failed during export planning.",
                details=str(exc),
            ) from exc

        raw.setdefault("deliverable_type", deliverable_type)
        raw.setdefault("manifest_version", manifest_version)
        try:
            plan = SLIDE_PLAN_ADAPTER.validate_python(raw)
        except ValidationError as exc:
            raise DomainValidationError(
                "AI returned an invalid slide plan.",
                details=exc.errors(),
            ) from exc
        self._validate_plan_against_manifest(plan, manifest)
        return plan

    def _build_fallback_plan(
        self,
        *,
        project: Project,
        graph: WorkspaceGraph,
        deliverable_type: DeliverableType,
        manifest_version: str,
    ) -> SlidePlan:
        warnings = self._build_warnings(graph)
        if deliverable_type == "pitch_deck":
            steps = self._build_pitch_deck_steps(
                project=project,
                graph=graph,
            )
        else:
            steps = self._build_business_document_steps(
                project=project,
                graph=graph,
            )
        return SlidePlan(
            deliverable_type=deliverable_type,
            manifest_version=manifest_version,
            steps=steps,
            warnings=warnings,
        )

    def _build_pitch_deck_steps(
        self,
        *,
        project: Project,
        graph: WorkspaceGraph,
    ) -> list[SlideStep]:
        nodes_by_type = self._group_nodes(graph)
        problem = self._first_node(nodes_by_type, "problem")
        solution = self._first_node(nodes_by_type, "solution", "objective", "opportunity", "resource")
        objective = self._first_node(nodes_by_type, "objective", "opportunity", "resource")
        evidence_nodes = self._evidence_nodes(graph)
        problem_headline = self._problem_headline(problem, project)
        problem_points = self._problem_points(problem, nodes_by_type)
        solution_headline = self._solution_headline(solution, objective, project)
        solution_description = self._solution_description(solution, objective, problem, project)
        solution_points = self._solution_points(nodes_by_type, solution, objective)

        steps = [
            SlideStep(
                component_key="pitch_deck.cover",
                title=project.name,
                variables={
                    "title": project.name,
                    "tagline": project.description
                    or (problem.title if problem else None)
                    or "Structured export generated from the current workspace graph.",
                    "author": self.actor.name,
                    "date": datetime.now().strftime("%d %b %Y"),
                },
                source_node_ids=[node.id for node in [problem] if node is not None],
            ),
            SlideStep(
                component_key="pitch_deck.problem",
                title=problem_headline,
                variables={
                    "main_problem": problem_headline,
                    "sub_points": problem_points,
                    "statistic": self._evidence_line(evidence_nodes[0]) if evidence_nodes else None,
                },
                source_node_ids=[
                    node.id
                    for node in [
                        problem,
                        *(
                            [evidence_nodes[0]]
                            if evidence_nodes
                            else []
                        ),
                    ]
                    if node is not None
                ],
            ),
            SlideStep(
                component_key="pitch_deck.solution",
                title=solution_headline,
                variables={
                    "headline": solution_headline,
                    "description": solution_description,
                    "key_points": solution_points,
                },
                source_node_ids=[node.id for node in [solution] if node is not None],
            ),
        ]

        for evidence_node in evidence_nodes[:2]:
            steps.append(
                SlideStep(
                    component_key="pitch_deck.metric",
                    title=evidence_node.title,
                    variables={
                        "headline": evidence_node.title,
                        "metric_value": self._extract_metric_value(
                            f"{evidence_node.title} {evidence_node.description}"
                        ),
                        "metric_label": self._metric_label(evidence_node),
                        "source_url": evidence_node.source_url,
                    },
                    source_node_ids=[evidence_node.id],
                )
            )

        steps.append(
            SlideStep(
                component_key="pitch_deck.closing",
                title=objective.title if objective else "Next decision checkpoint",
                variables={
                    "headline": objective.title if objective else "Ready for review and export.",
                    "ask": objective.description
                    if objective and objective.description
                    else "Review the graph, confirm branch priorities, and export the next revision.",
                    "contact": self.actor.email,
                },
                source_node_ids=[node.id for node in [objective] if node is not None],
            )
        )
        return steps

    def _build_business_document_steps(
        self,
        *,
        project: Project,
        graph: WorkspaceGraph,
    ) -> list[SlideStep]:
        nodes_by_type = self._group_nodes(graph)
        problem = self._first_node(nodes_by_type, "problem")
        solution = self._first_node(nodes_by_type, "solution", "objective", "opportunity", "resource")
        objective = self._first_node(nodes_by_type, "objective", "opportunity", "resource")
        evidence_nodes = self._evidence_nodes(graph)
        next_step_nodes = self._titles_from_nodes(
            [
                *(nodes_by_type.get("objective") or []),
                *(nodes_by_type.get("opportunity") or []),
                *(nodes_by_type.get("resource") or []),
                *(nodes_by_type.get("solution") or []),
            ],
            exclude_ids={solution.id} if solution else set(),
            limit=4,
        )
        if not next_step_nodes:
            next_step_nodes = list(GENERIC_RECOMMENDATION_POINTS)

        summary = self._business_summary(project, problem, solution, objective)
        problem_title = problem.title if problem else "Problem analysis"
        problem_body = self._business_problem_body(problem)
        recommendation_title = solution.title if solution else "Recommended approach"
        recommendation_body = self._solution_description(solution, objective, problem, project)

        risk_items = self._build_risk_items(graph, nodes_by_type)

        return [
            SlideStep(
                component_key="business_document.executive_summary",
                title="Executive summary",
                variables={
                    "title": "Executive summary",
                    "summary": summary,
                    "highlights": self._problem_points(problem, nodes_by_type)[:3] or next_step_nodes[:3],
                },
                source_node_ids=[
                    node.id
                    for node in [problem, solution, objective]
                    if node is not None
                ],
            ),
            SlideStep(
                component_key="business_document.problem_analysis",
                title=problem_title,
                variables={
                    "title": problem_title,
                    "body": problem_body,
                    "evidence": [self._evidence_line(node) for node in evidence_nodes[:4]],
                },
                source_node_ids=[
                    node.id
                    for node in [problem, *evidence_nodes[:4]]
                    if node is not None
                ],
            ),
            SlideStep(
                component_key="business_document.recommendation",
                title=recommendation_title,
                variables={
                    "title": recommendation_title,
                    "body": recommendation_body,
                    "next_steps": next_step_nodes,
                },
                source_node_ids=[node.id for node in [solution, objective] if node is not None],
            ),
            SlideStep(
                component_key="business_document.risk_register",
                title="Risk register",
                variables={
                    "title": "Risk register",
                    "risks": risk_items,
                },
                source_node_ids=[
                    UUID(item["source_node_id"])
                    for item in risk_items
                    if item.get("source_node_id")
                ],
            ),
        ]

    def _build_warnings(self, graph: WorkspaceGraph) -> list[str]:
        warnings: list[str] = []
        validation = graph.metadata.validation
        if not validation.is_valid and validation.issues:
            issue_summary = " ".join(issue.message for issue in validation.issues[:2]).strip()
            warnings.append(
                f"Resolve workspace validation issues before sharing this export. {issue_summary}".strip()
            )
        if not graph.nodes:
            warnings.append(
                "Workspace is empty. Export output uses placeholder narrative until the graph is populated."
            )
        if not any(node.type.value == "solution" for node in graph.nodes):
            warnings.append(
                "No solution nodes found. Recommendation sections use fallback copy."
            )
        if not self._evidence_nodes(graph):
            warnings.append(
                "No evidence or metric nodes found. Add supporting evidence for a stronger export."
            )
        return warnings

    def _group_nodes(self, graph: WorkspaceGraph) -> dict[str, list[GraphNode]]:
        grouped: dict[str, list[GraphNode]] = {}
        for node in graph.nodes:
            grouped.setdefault(node.type.value, []).append(node)
        return grouped

    def _first_node(
        self,
        nodes_by_type: dict[str, list[GraphNode]],
        *node_types: str,
    ) -> GraphNode | None:
        for node_type in node_types:
            nodes = nodes_by_type.get(node_type) or []
            if nodes:
                return nodes[0]
        return None

    def _evidence_nodes(self, graph: WorkspaceGraph) -> list[GraphNode]:
        evidence_nodes = [
            node
            for node in graph.nodes
            if node.type.value in EVIDENCE_NODE_TYPES
            or node.is_enrichment
            or node.source.value == "web"
        ]
        return evidence_nodes

    def _distinct_titles(
        self,
        nodes: list[GraphNode],
        *,
        exclude_ids: set[UUID] | None = None,
        limit: int,
    ) -> list[str]:
        return self._titles_from_nodes(nodes, exclude_ids=exclude_ids, limit=limit)

    def _titles_from_nodes(
        self,
        nodes: list[GraphNode],
        *,
        exclude_ids: set[UUID] | None = None,
        limit: int,
    ) -> list[str]:
        excluded = exclude_ids or set()
        titles: list[str] = []
        seen: set[str] = set()
        for node in nodes:
            if node.id in excluded:
                continue
            title = node.title.strip()
            if not title:
                continue
            lowered = title.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            titles.append(title)
            if len(titles) >= limit:
                break
        return titles

    def _evidence_line(self, node: GraphNode) -> str:
        description = node.description.strip()
        if description:
            return f"{node.title}: {description}"
        return node.title

    def _metric_label(self, node: GraphNode) -> str:
        description = node.description.strip()
        if description:
            return description
        return node.title

    def _problem_headline(self, node: GraphNode | None, project: Project) -> str:
        if node is None:
            return "Problem framing is not defined yet."
        for candidate in self._text_candidates(node):
            first_sentence = self._first_sentence(candidate)
            clipped = self._clip_text(first_sentence, 88)
            if clipped:
                return clipped
        return self._clip_text(project.description or "Problem framing is not defined yet.", 88)

    def _problem_points(
        self,
        node: GraphNode | None,
        nodes_by_type: dict[str, list[GraphNode]],
    ) -> list[str]:
        fallback_points = self._distinct_titles(
            [
                *(nodes_by_type.get("assumption") or []),
                *(nodes_by_type.get("risk") or []),
                *(nodes_by_type.get("constraint") or []),
                *(nodes_by_type.get("problem") or []),
            ],
            exclude_ids={node.id} if node else set(),
            limit=4,
        )
        if node is None:
            return fallback_points

        headline = self._clip_text(self._first_sentence(node.title), 88)
        points: list[str] = []
        for sentence in self._sentences_from_node(node):
            clipped = self._clip_text(sentence, 120)
            if not clipped:
                continue
            if headline and clipped.lower() == headline.lower():
                continue
            replaced = False
            for index, existing in enumerate(points):
                if existing.lower() == clipped.lower():
                    replaced = True
                    break
                if existing.lower().startswith(clipped.lower()):
                    replaced = True
                    break
                if clipped.lower().startswith(existing.lower()):
                    points[index] = clipped
                    replaced = True
                    break
            if replaced:
                continue
            points.append(clipped)
            if len(points) >= 4:
                break
        if points:
            return points
        return fallback_points

    def _solution_headline(
        self,
        solution: GraphNode | None,
        objective: GraphNode | None,
        project: Project,
    ) -> str:
        preferred = solution or objective
        if preferred is not None:
            return self._clip_text(self._first_sentence(preferred.title), 84)
        return "Stabilize the case with targeted recovery actions."

    def _solution_description(
        self,
        solution: GraphNode | None,
        objective: GraphNode | None,
        problem: GraphNode | None,
        project: Project,
    ) -> str:
        preferred = solution or objective
        if preferred is not None:
            for candidate in self._text_candidates(preferred):
                clipped = self._clip_text(candidate, 240)
                if clipped:
                    return clipped
        if problem is not None:
            return (
                "Translate the problem into a tighter response plan with explicit actions, "
                "focused offers, and measurable outcome tracking."
            )
        return "Add solution or objective nodes to turn the graph into an export-ready recommendation."

    def _solution_points(
        self,
        nodes_by_type: dict[str, list[GraphNode]],
        solution: GraphNode | None,
        objective: GraphNode | None,
    ) -> list[str]:
        points = self._distinct_titles(
            [
                *(nodes_by_type.get("solution") or []),
                *(nodes_by_type.get("objective") or []),
                *(nodes_by_type.get("opportunity") or []),
                *(nodes_by_type.get("resource") or []),
            ],
            exclude_ids={node.id for node in [solution, objective] if node is not None},
            limit=4,
        )
        if points:
            return points
        return list(GENERIC_RECOMMENDATION_POINTS)

    def _business_summary(
        self,
        project: Project,
        problem: GraphNode | None,
        solution: GraphNode | None,
        objective: GraphNode | None,
    ) -> str:
        summary_parts = [
            self._clip_text(project.description or "", 140),
            self._solution_description(solution, objective, problem, project),
        ]
        combined = " ".join(part for part in summary_parts if part)
        if combined.strip():
            return combined.strip()
        return (
            "This document was generated from the current workspace graph. "
            "Add problem, solution, and evidence nodes to deepen the narrative."
        )

    def _business_problem_body(self, problem: GraphNode | None) -> str:
        if problem is None:
            return "The graph does not yet include a fully-defined problem analysis."
        sentences = self._sentences_from_node(problem)
        if len(sentences) > 1:
            return " ".join(self._clip_text(sentence, 140) for sentence in sentences[1:3] if sentence).strip()
        for candidate in self._text_candidates(problem):
            clipped = self._clip_text(candidate, 240)
            if clipped:
                return clipped
        return "The graph does not yet include a fully-defined problem analysis."

    def _extract_metric_value(self, text: str) -> str:
        patterns = [
            r"\b\d+(?:\.\d+)?%",
            r"\b\d+(?:\.\d+)?x\b",
            r"\b\d+(?:\.\d+)?(?:k|m|b)\b",
            r"\$\d+(?:,\d{3})*(?:\.\d+)?",
            r"\b\d+(?:,\d{3})*(?:\.\d+)?\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(0)
        title_words = text.strip().split()
        return " ".join(title_words[:3]) if title_words else "Evidence"

    def _text_candidates(self, node: GraphNode) -> list[str]:
        return [
            value.strip()
            for value in [node.title, node.description]
            if isinstance(value, str) and value.strip()
        ]

    def _sentences_from_node(self, node: GraphNode) -> list[str]:
        sentences: list[str] = []
        seen: set[str] = set()
        for candidate in self._text_candidates(node):
            for sentence in self._split_sentences(candidate):
                normalized = sentence.strip()
                lowered = normalized.lower()
                if not normalized or lowered in seen:
                    continue
                seen.add(lowered)
                sentences.append(normalized)
        return sentences

    def _split_sentences(self, text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", text.strip())
        if not normalized:
            return []
        parts = re.split(r"(?<=[.!?])\s+", normalized)
        return [part.strip(" -") for part in parts if part.strip(" -")]

    def _first_sentence(self, text: str) -> str:
        parts = self._split_sentences(text)
        return parts[0] if parts else text.strip()

    def _clip_text(self, text: str, max_length: int) -> str:
        normalized = re.sub(r"\s+", " ", text.strip())
        if len(normalized) <= max_length:
            return normalized
        clipped = normalized[: max_length + 1]
        if " " in clipped:
            clipped = clipped.rsplit(" ", 1)[0]
        return clipped.rstrip(" ,.;:") + "..."

    def _build_risk_items(
        self,
        graph: WorkspaceGraph,
        nodes_by_type: dict[str, list[GraphNode]],
    ) -> list[dict[str, str | None]]:
        node_map = {node.id: node for node in graph.nodes}
        adjacency: dict[UUID, list[GraphNode]] = {}
        for edge in graph.edges:
            source_neighbors = adjacency.setdefault(edge.source, [])
            if edge.target in node_map:
                source_neighbors.append(node_map[edge.target])
            target_neighbors = adjacency.setdefault(edge.target, [])
            if edge.source in node_map:
                target_neighbors.append(node_map[edge.source])

        candidates = [
            *(nodes_by_type.get("risk") or []),
            *(nodes_by_type.get("constraint") or []),
        ]
        if not candidates:
            return [
                {
                    "title": "Sparse workspace coverage",
                    "description": "The current graph does not yet include explicit risk or constraint nodes.",
                    "mitigation": "Add risk nodes before sharing the export externally.",
                    "source_node_id": None,
                }
            ]

        items: list[dict[str, str | None]] = []
        for node in candidates[:6]:
            mitigation = None
            for neighbor in adjacency.get(node.id, []):
                if neighbor.type.value in {"solution", "objective", "opportunity", "resource"}:
                    mitigation = neighbor.title
                    break
            items.append(
                {
                    "title": node.title,
                    "description": node.description or node.title,
                    "mitigation": mitigation,
                    "source_node_id": str(node.id),
                }
            )
        return items

    def _plan_system_prompt(self, deliverable_type: DeliverableType) -> str:
        format_hint = (
            "A4 landscape, one slide per step"
            if deliverable_type == "pitch_deck"
            else "A4 portrait, one section per step"
        )
        return (
            "You plan an export for a business-case knowledge graph. "
            "Return JSON only with keys 'deliverable_type', 'manifest_version', "
            "'steps' (list), 'warnings' (list of strings). "
            "Every step must reference an existing manifest component via 'component_key', "
            "and its 'variables' must satisfy that component's documented schema. "
            f"Deliverable format: {format_hint}. "
            "There is no fixed slide order. Derive a clear narrative from the graph. "
            "Web-enriched nodes may be used as evidence and should preserve source_url where relevant."
        )

    def _validate_plan_against_manifest(
        self,
        plan: SlidePlan,
        manifest: dict[str, Any],
    ) -> None:
        components = manifest.get("components") or []
        if not isinstance(components, list):
            raise DomainValidationError("Manifest 'components' must be a list.")
        components_by_key = {
            component.get("key"): component
            for component in components
            if isinstance(component, dict) and component.get("key")
        }
        errors: list[dict[str, Any]] = []

        for step in plan.steps:
            component = components_by_key.get(step.component_key)
            if component is None:
                errors.append(
                    {
                        "component_key": step.component_key,
                        "reason": "unknown_component",
                    }
                )
                continue
            if component.get("deliverable_type") != plan.deliverable_type:
                errors.append(
                    {
                        "component_key": step.component_key,
                        "reason": "wrong_deliverable_type",
                        "expected": component.get("deliverable_type"),
                        "actual": plan.deliverable_type,
                    }
                )
            variable_spec = component.get("variables") or {}
            if not isinstance(variable_spec, dict):
                continue
            for variable_name, spec in variable_spec.items():
                if not isinstance(spec, dict):
                    continue
                value = step.variables.get(variable_name)
                if spec.get("required") and not self._has_value(value):
                    errors.append(
                        {
                            "component_key": step.component_key,
                            "variable": variable_name,
                            "reason": "missing_required_variable",
                        }
                    )
                    continue
                if value is not None and not self._matches_manifest_type(value, str(spec.get("type"))):
                    errors.append(
                        {
                            "component_key": step.component_key,
                            "variable": variable_name,
                            "reason": "invalid_variable_type",
                            "expected": spec.get("type"),
                            "actual": type(value).__name__,
                        }
                    )
        if errors:
            raise DomainValidationError(
                "Slide plan does not satisfy the export component manifest.",
                details=errors,
            )

    def _matches_manifest_type(self, value: Any, manifest_type: str) -> bool:
        if manifest_type == "string":
            return isinstance(value, str)
        if manifest_type == "string[]":
            return isinstance(value, list) and all(isinstance(item, str) for item in value)
        if manifest_type == "object[]":
            return isinstance(value, list) and all(isinstance(item, dict) for item in value)
        return True

    def _has_value(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return len(value) > 0
        return True

    def _wrap_document(self, plan: SlidePlan, rendered_steps: list[str]) -> str:
        title = "Pitch deck export" if plan.deliverable_type == "pitch_deck" else "Business document export"
        return "\n".join(
            [
                "<!doctype html>",
                '<html lang="en">',
                "<head>",
                '  <meta charset="utf-8" />',
                '  <meta name="viewport" content="width=device-width, initial-scale=1" />',
                f"  <title>{html.escape(title)}</title>",
                f"  <style>{self._document_styles(plan.deliverable_type)}</style>",
                "</head>",
                f'<body class="{plan.deliverable_type}">',
                *rendered_steps,
                "</body>",
                "</html>",
            ]
        )

    def _document_styles(self, deliverable_type: DeliverableType) -> str:
        page_rule = (
            "@page { size: A4 landscape; margin: 0; }"
            if deliverable_type == "pitch_deck"
            else "@page { size: A4 portrait; margin: 14mm; }"
        )
        return (
            f"{page_rule}"
            " :root { color-scheme: light; font-family: 'Helvetica Neue', Arial, sans-serif; }"
            " * { box-sizing: border-box; }"
            " body { margin: 0; background: #f3f7f4; color: #092a22; }"
            " body.pitch_deck { background: #0b1d18; }"
            " .slide, .section { break-after: page; page-break-after: always; }"
            " .slide { width: 297mm; height: 210mm; padding: 22mm 24mm; display: flex; flex-direction: column; justify-content: space-between; background: linear-gradient(180deg, #f6fbf7 0%, #e5f3e9 100%); }"
            " .slide-cover, .slide-closing { background: radial-gradient(circle at top left, #ccf8d8 0%, #e5f3e9 38%, #d2eee2 100%); }"
            " .slide-title, .slide-header h1, .section h1 { margin: 0; line-height: 1.05; letter-spacing: -0.04em; }"
            " .slide-title { font-size: 34pt; max-width: 10.5in; }"
            " .slide-tagline, .description, .summary, .body, .ask, .contact, .source, .metric-label { font-size: 14pt; line-height: 1.55; }"
            " .slide-header { display: grid; gap: 10px; }"
            " .slide-problem h1, .slide-solution h1 { max-width: 10.7in; font-size: 29pt; line-height: 1.08; }"
            " .slide-problem .sub-points, .slide-solution .key-points { max-width: 8.8in; }"
            " .slide-solution .description { max-width: 8.8in; margin-top: 16px; }"
            " .eyebrow { display: inline-flex; align-self: flex-start; font-size: 9pt; letter-spacing: 0.22em; text-transform: uppercase; color: #0f6c53; }"
            " .sub-points, .key-points, .highlights, .next-steps { margin: 18px 0 0; padding-left: 24px; font-size: 14pt; line-height: 1.6; }"
            " .metric-display { display: grid; gap: 8px; margin: 24px 0; }"
            " .metric-value { font-size: 44pt; font-weight: 700; letter-spacing: -0.05em; }"
            " .metric-label { color: #255346; }"
            " .stat { margin-top: auto; padding: 16px 18px; border-radius: 18px; background: rgba(12, 109, 82, 0.1); font-size: 13pt; line-height: 1.5; }"
            " .slide-meta { display: flex; gap: 18px; font-size: 11pt; color: #255346; }"
            " .section { min-height: calc(297mm - 28mm); padding: 0; display: grid; gap: 16px; background: #ffffff; }"
            " .section .body, .section .summary { white-space: pre-wrap; }"
            " .evidence, .risks { margin-top: 8px; }"
            " .evidence h2, .section h2 { margin: 0 0 10px; font-size: 13pt; letter-spacing: -0.02em; }"
            " .evidence ul { margin: 0; padding-left: 22px; font-size: 12pt; line-height: 1.6; }"
            " table.risks { width: 100%; border-collapse: collapse; font-size: 11pt; }"
            " table.risks th, table.risks td { border: 1px solid #cfe2d7; padding: 10px 12px; text-align: left; vertical-align: top; }"
            " table.risks th { background: #edf6f0; }"
            " a { color: #0a6c53; text-decoration: none; }"
        )

    def _render_template(self, template: str, context: dict[str, Any]) -> str:
        rendered = self._render_each_blocks(template, context)
        rendered = self._render_if_blocks(rendered, context)
        rendered = self._render_variables(rendered, context)
        return rendered

    def _render_each_blocks(self, template: str, context: dict[str, Any]) -> str:
        pattern = re.compile(r"{{#each\s+([^}]+)}}(.*?){{/each}}", flags=re.DOTALL)
        while True:
            match = pattern.search(template)
            if match is None:
                return template
            expression = match.group(1).strip()
            block = match.group(2)
            items = self._resolve_value(expression, context)
            rendered_block = ""
            if isinstance(items, list):
                parts: list[str] = []
                for item in items:
                    child_context = dict(context)
                    child_context["this"] = item
                    parts.append(self._render_template(block, child_context))
                rendered_block = "".join(parts)
            template = template[: match.start()] + rendered_block + template[match.end() :]

    def _render_if_blocks(self, template: str, context: dict[str, Any]) -> str:
        pattern = re.compile(r"{{#if\s+([^}]+)}}(.*?){{/if}}", flags=re.DOTALL)
        while True:
            match = pattern.search(template)
            if match is None:
                return template
            expression = match.group(1).strip()
            block = match.group(2)
            truthy = self._is_truthy(self._resolve_value(expression, context))
            if "{{else}}" in block:
                true_branch, false_branch = block.split("{{else}}", 1)
            else:
                true_branch, false_branch = block, ""
            chosen = true_branch if truthy else false_branch
            rendered = self._render_template(chosen, context)
            template = template[: match.start()] + rendered + template[match.end() :]

    def _render_variables(self, template: str, context: dict[str, Any]) -> str:
        pattern = re.compile(r"{{\s*([^#/][^}]*)\s*}}")

        def replace(match: re.Match[str]) -> str:
            expression = match.group(1).strip()
            if expression == "else":
                return ""
            value = self._resolve_value(expression, context)
            if value is None:
                return ""
            if isinstance(value, (dict, list)):
                return html.escape(json.dumps(value))
            return html.escape(str(value))

        return pattern.sub(replace, template)

    def _resolve_value(self, expression: str, context: dict[str, Any]) -> Any:
        path = expression.strip()
        if not path:
            return None
        if path == "this":
            return context.get("this")

        parts = path.split(".")
        current: Any
        if parts[0] == "this":
            current = context.get("this")
            parts = parts[1:]
        else:
            current = context.get(parts[0])
            parts = parts[1:]

        for part in parts:
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(part)
                continue
            current = getattr(current, part, None)
        return current

    def _is_truthy(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return len(value) > 0
        return bool(value)

    def _build_artifact_paths(self, job_id: UUID) -> tuple[Path, Path]:
        job_dir = EXPORT_ARTIFACTS_DIR / str(job_id)
        return job_dir / "index.html", job_dir / "export.pdf"

    def _render_pdf_file(
        self,
        *,
        html_path: Path,
        pdf_path: Path,
        deliverable_type: DeliverableType,
    ) -> None:
        if not PLAYWRIGHT_RENDER_SCRIPT.exists():
            raise ServiceUnavailableError(
                "Playwright export renderer is missing.",
                details={"expected_path": str(PLAYWRIGHT_RENDER_SCRIPT)},
            )
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    "node",
                    str(PLAYWRIGHT_RENDER_SCRIPT),
                    str(html_path),
                    str(pdf_path),
                    deliverable_type,
                ],
                cwd=str(FRONTEND_ROOT),
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise ServiceUnavailableError(
                "Node.js runtime is unavailable for PDF rendering.",
            ) from exc
        except subprocess.CalledProcessError as exc:
            details = exc.stderr.strip() or exc.stdout.strip() or "Unknown Playwright renderer failure."
            raise ServiceUnavailableError(
                "Playwright failed to render the export PDF.",
                details=details,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ServiceUnavailableError(
                "PDF rendering timed out.",
                details=str(exc),
            ) from exc

    def _build_pdf_filename(self, job: ExportJob) -> str:
        project = self.project_repository.get_by_id(job.project_id)
        project_name = project.name if project is not None else "qony-export"
        slug = self._slugify(project_name)
        suffix = "pitch-deck" if job.deliverable_type == "pitch_deck" else "business-document"
        return f"{slug}-{suffix}.pdf"

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "qony-export"
