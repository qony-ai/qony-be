from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.core.security import Actor
from app.domain.enums import ExportJobStatus, ExportType, UsageEventType
from app.models.export_job import ExportJob
from app.repositories.projects import ProjectRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository
from app.schemas.export import ExportJobRead, ExportRequest, export_job_to_read
from app.services.ai_router import AIRouter
from app.services.graph_engine import GraphEngine
from app.services.usage_service import UsageService
from app.utils.s3_utils import upload_file

logger = logging.getLogger(__name__)


class ExportEngine:
    def __init__(self, *, session: Session, settings: Settings, actor: Actor) -> None:
        self.session = session
        self.settings = settings
        self.actor = actor
        self.airouter = AIRouter(settings)
        self.graph_engine = GraphEngine(session=session, settings=settings, actor=actor)
        self.user_repository = UserRepository(session)
        self.project_repository = ProjectRepository(session)
        self.workspace_repository = WorkspaceRepository(session)
        self.usage_service = UsageService(session=session, actor=actor)

    def create_export(self, graph_id: UUID, payload: ExportRequest) -> ExportJobRead:
        graph = self.graph_engine.get_graph(graph_id)
        project = self.project_repository.get_by_id(graph.project_id)
        if project is None:
            raise NotFoundError("Project not found.")
        user = self.user_repository.get_or_create(
            email=self.actor.email,
            name=self.actor.name,
            external_auth_id=self.actor.auth_user_id,
        )

        job = ExportJob(
            project_id=graph.project_id,
            workspace_id=graph.id,
            requested_by_user_id=user.id,
            export_type=payload.export_type.value,
            status=ExportJobStatus.PROCESSING.value,
            metadata_json={"requested_by": self.actor.email},
        )
        self.session.add(job)
        self.session.flush()

        manifest = self._load_component_manifest()
        slide_plan = self._build_slide_plan(graph.model_dump(mode="json"), manifest, payload.export_type)
        html = self._render_export_html(slide_plan, payload.export_type)

        output_dir = Path("/tmp/qony-export-engine")
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / f"{job.id}.html"
        html_path.write_text(html, encoding="utf-8")
        output_path = self._render_pdf_if_possible(html_path, payload.export_type)
        output_url = upload_file(str(output_path), key=f"exports/{output_path.name}")

        job.status = ExportJobStatus.COMPLETED.value
        job.slide_plan_json = slide_plan
        job.output_url = output_url
        job.metadata_json = {
            **job.metadata_json,
            "html_path": str(html_path),
            "output_path": str(output_path),
        }
        self.usage_service.record_event(
            event_type=UsageEventType.EXPORT,
            project_id=graph.project_id,
            metadata={"export_type": payload.export_type.value},
        )
        self.session.commit()
        self.session.refresh(job)
        return export_job_to_read(job)

    def get_export_job(self, job_id: UUID) -> ExportJobRead:
        statement = select(ExportJob).where(ExportJob.id == job_id)
        job = self.session.scalar(statement)
        if job is None:
            raise NotFoundError("Export job not found.")
        return export_job_to_read(job)

    def _load_component_manifest(self) -> dict:
        manifest_path = (
            Path(__file__).resolve().parents[3]
            / "qony-fe"
            / "public"
            / "export-components"
            / "index.json"
        )
        if manifest_path.exists():
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        return {"components": []}

    def _build_slide_plan(self, graph_payload: dict, manifest: dict, export_type: ExportType) -> dict:
        components = manifest.get("components", [])
        if self.settings.effective_ai_provider != "stub":
            try:
                route = self.airouter.complete_json(
                    use_case="generation",
                    system_prompt=(
                        "You plan exports from a typed business graph. "
                        "Return JSON with key 'slides', each item containing component_path and variables."
                    ),
                    user_prompt=json.dumps(
                        {
                            "export_type": export_type.value,
                            "graph": graph_payload,
                            "components": components,
                        }
                    ),
                )
                slides = route.payload.get("slides", [])
                if isinstance(slides, list) and slides:
                    return {
                        "export_type": export_type.value,
                        "slides": slides,
                        "component_count": len(slides),
                        "planned_by": route.provider,
                    }
            except Exception:
                logger.warning("export_ai_planning_failed", exc_info=True)

        default_component = next(
            (
                component
                for component in components
                if component.get("export_type") in {export_type.value, "any"}
            ),
            None,
        )
        if default_component is None:
            default_component = {
                "id": "fallback",
                "path": "slides/problem-statement.html",
                "variables": ["title", "body"],
            }

        slides = []
        for node in graph_payload.get("nodes", [])[:8]:
            slides.append(
                {
                    "component_id": default_component.get("id"),
                    "component_path": default_component.get("path"),
                    "variables": {
                        "title": node.get("title"),
                        "body": node.get("description") or "",
                        "type": node.get("type"),
                    },
                }
            )

        if not slides:
            slides.append(
                {
                    "component_id": default_component.get("id"),
                    "component_path": default_component.get("path"),
                    "variables": {
                        "title": "Empty graph",
                        "body": "No graph nodes are available for export yet.",
                        "type": "problem",
                    },
                }
            )

        return {
            "export_type": export_type.value,
            "slides": slides,
            "component_count": len(slides),
        }

    def _render_export_html(self, slide_plan: dict, export_type: ExportType) -> str:
        page_size = "297mm 210mm" if export_type == ExportType.PITCH_DECK else "210mm 297mm"
        slide_markup = []
        for slide in slide_plan.get("slides", []):
            component_path = (
                Path(__file__).resolve().parents[3]
                / "qony-fe"
                / "public"
                / "export-components"
                / slide["component_path"]
            )
            template = component_path.read_text(encoding="utf-8") if component_path.exists() else "<section><h1>{{title}}</h1><p>{{body}}</p></section>"
            slide_markup.append(self._render_template(template, slide.get("variables", {})))

        return (
            "<!doctype html><html><head><meta charset='utf-8' />"
            "<style>"
            f"@page {{ size: {page_size}; margin: 0; }}"
            "body{margin:0;font-family:Arial,sans-serif;background:#f5f0e8;color:#18220f;}"
            ".page{page-break-after:always;min-height:100vh;display:flex;align-items:stretch;}"
            ".slide{width:100%;padding:32px;box-sizing:border-box;}"
            "</style></head><body>"
            + "".join(f"<div class='page'>{markup}</div>" for markup in slide_markup)
            + "</body></html>"
        )

    def _render_template(self, template: str, variables: dict) -> str:
        rendered = template
        for key, value in variables.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value or ""))
        rendered = re.sub(r"\{\{#if [^}]+\}\}|\{\{\/if\}\}", "", rendered)
        rendered = re.sub(r"\{\{#each [^}]+\}\}|\{\{\/each\}\}", "", rendered)
        return rendered

    def _render_pdf_if_possible(self, html_path: Path, export_type: ExportType) -> Path:
        script_path = Path(__file__).resolve().parents[3] / "qony-fe" / "scripts" / "render-export-pdf.mjs"
        if not script_path.exists():
            return html_path
        if shutil.which("node") is None:
            return html_path

        pdf_path = html_path.with_suffix(".pdf")
        try:
            subprocess.run(
                [
                    "node",
                    str(script_path),
                    str(html_path),
                    str(pdf_path),
                    export_type.value,
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as exc:
            logger.warning("playwright_pdf_render_failed", exc_info=exc)
            return html_path

        return pdf_path if pdf_path.exists() else html_path
