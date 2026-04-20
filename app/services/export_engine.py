"""Library-based export engine skeleton.

Produces a pitch deck or business document PDF from a workspace graph
using the HTML component library at ``qony-fe/public/export-components/``.
Per spec (``resources/COMPONENT_LIBRARY.md``) the flow is:

1. AI router reads the workspace graph + component manifest and returns
   a :class:`SlidePlan` — an ordered list of ``(component_key, variables)``.
2. Backend renders each step with Handlebars-style placeholders into
   HTML, then pipes the HTML through Playwright to produce the PDF.
3. The whole run lives as one :class:`ExportJob` row with status
   transitions ``pending → planning → rendering → completed | failed``.

This module is a skeleton: the planning + HTML render + PDF render
implementations land in follow-up commits. What ships now:

* ``ExportEngine.create_job`` — persists a ``pending`` job and returns
  its read model (used by the future ``POST /export/jobs`` route).
* ``ExportEngine.plan_slides`` — delegates to the AI router with the
  system/user prompts for plan generation. Parses the JSON response.
* ``ExportEngine.render_html`` / ``render_pdf`` — raise
  :class:`ServiceUnavailableError` until the renderers land. The status
  transition to ``rendering`` is still authoritative on the DB side.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    AIProviderError,
    DomainValidationError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.core.security import Actor
from app.models.export_job import ExportJob
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
from app.schemas.workspace import WorkspaceGraph
from app.services.ai_router import get_ai_router
from app.services.graph_mapper import workspace_to_graph


SLIDE_PLAN_ADAPTER = TypeAdapter(SlidePlan)

EXPORT_COMPONENTS_DIR = (
    Path(__file__).resolve().parents[3] / "qony-fe" / "public" / "export-components"
)
MANIFEST_FILENAME = "index.json"


class ExportEngine:
    def __init__(self, *, session: Session, settings: Settings, actor: Actor) -> None:
        self.session = session
        self.settings = settings
        self.actor = actor
        self.user_repository = UserRepository(session)
        self.project_repository = ProjectRepository(session)
        self.workspace_repository = WorkspaceRepository(session)
        self.router = get_ai_router(settings)

    # ------------------------------------------------------------------ jobs

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

    def get_job(self, job_id: UUID) -> ExportJobRead:
        job = self.session.get(ExportJob, job_id)
        if job is None:
            raise NotFoundError("Export job not found.")
        return export_job_to_read(job)

    # ----------------------------------------------------------------- plan

    def plan_slides(
        self,
        *,
        graph: WorkspaceGraph,
        deliverable_type: DeliverableType,
    ) -> SlidePlan:
        manifest, manifest_version = self._load_manifest()
        system_prompt = self._plan_system_prompt(deliverable_type)
        user_prompt = json.dumps(
            {
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

    # --------------------------------------------------------------- render

    def render_html(self, plan: SlidePlan) -> str:  # pragma: no cover - skeleton
        raise ServiceUnavailableError(
            "Export HTML renderer is not wired up yet. "
            "Handlebars template rendering lands in a follow-up commit.",
        )

    def render_pdf(
        self,
        *,
        html: str,
        deliverable_type: DeliverableType,
    ) -> bytes:  # pragma: no cover - skeleton
        raise ServiceUnavailableError(
            "Playwright PDF renderer is not wired up yet. "
            "Page format: A4 landscape for pitch_deck, A4 portrait for business_document.",
        )

    # ----------------------------------------------------------------- utils

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

    def _load_manifest(self) -> tuple[dict[str, Any], str]:
        manifest_path = EXPORT_COMPONENTS_DIR / MANIFEST_FILENAME
        if not manifest_path.exists():
            raise ServiceUnavailableError(
                "Export component manifest is missing.",
                details={"expected_path": str(manifest_path)},
            )
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
        version = hashlib.sha256(raw).hexdigest()[:16]
        return manifest, version

    def _plan_system_prompt(self, deliverable_type: DeliverableType) -> str:
        format_hint = (
            "A4 landscape, one slide per step"
            if deliverable_type == "pitch_deck"
            else "A4 portrait, one section per step"
        )
        return (
            "You plan an export for a business case knowledge graph. "
            "Return JSON only with keys 'deliverable_type', 'manifest_version', "
            "'steps' (list), 'warnings' (list of strings). "
            "Every step must reference an existing manifest component via 'component_key', "
            "and its 'variables' must satisfy that component's documented schema. "
            f"Deliverable format: {format_hint}. "
            "There is no fixed slide order — derive the narrative from the graph. "
            "Web-enriched nodes (is_enrichment=true) may be used as evidence; always cite source_url in variables."
        )

    def _validate_plan_against_manifest(
        self,
        plan: SlidePlan,
        manifest: dict[str, Any],
    ) -> None:
        components = manifest.get("components") or []
        if not isinstance(components, list):
            raise DomainValidationError(
                "Manifest 'components' must be a list.",
            )
        valid_keys = {
            component.get("key")
            for component in components
            if isinstance(component, dict) and component.get("key")
        }
        unknown = [step.component_key for step in plan.steps if step.component_key not in valid_keys]
        if unknown:
            raise DomainValidationError(
                "Slide plan references unknown component keys.",
                details={"unknown_component_keys": unknown},
            )
