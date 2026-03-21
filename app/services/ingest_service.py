from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import Actor
from app.repositories.ingest_jobs import IngestJobRepository
from app.repositories.projects import ProjectRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository
from app.schemas.ingest import IngestRequest, IngestResponseData, ingest_job_to_read
from app.services.ai_service import AIService
from app.services.graph_mapper import workspace_to_graph


class IngestService:
    def __init__(self, *, session: Session, settings: Settings, actor: Actor) -> None:
        self.session = session
        self.settings = settings
        self.actor = actor
        self.user_repository = UserRepository(session)
        self.project_repository = ProjectRepository(session)
        self.workspace_repository = WorkspaceRepository(session)
        self.ingest_job_repository = IngestJobRepository(session)
        self.ai_service = AIService(session=session, settings=settings, actor=actor)

    def ingest(self, payload: IngestRequest) -> IngestResponseData:
        user = self.user_repository.get_or_create(email=self.actor.email, name=self.actor.name)
        project = self._resolve_project(payload.project_id)
        if project is None:
            raise NotFoundError("Project not found.")
        workspace = self.workspace_repository.get_by_project_id(project.id)
        if workspace is None:
            raise NotFoundError("Workspace not found.")
        if workspace.nodes and not payload.replace_existing:
            raise ConflictError("Workspace already contains graph content. Use replace_existing to overwrite it.")

        job = self.ingest_job_repository.create_pending(
            project_id=project.id,
            workspace_id=workspace.id,
            requested_by_user_id=user.id,
            raw_text=payload.raw_text,
            source_filename=payload.source_filename,
            source_content_type=payload.source_content_type,
            provider=self.settings.ai_provider,
            metadata=payload.metadata,
        )
        self.session.commit()

        try:
            workspace = self.workspace_repository.get_by_project_id(project.id)
            if workspace is None:
                raise NotFoundError("Workspace not found after ingest job creation.")
            suggestion = self.ai_service.generate_ingest_graph(
                project_id=project.id,
                workspace_id=workspace.id,
                user_id=user.id,
                raw_text=payload.raw_text,
                workspace_version=workspace.version,
            )
            self.workspace_repository.sync_graph(workspace, suggestion.graph)
            refreshed_workspace = self.workspace_repository.get_by_project_id(project.id)
            if refreshed_workspace is None:
                raise NotFoundError("Workspace could not be reloaded after ingest.")
            self.ingest_job_repository.mark_completed(
                job,
                provider=suggestion.provider_result.provider,
                model=suggestion.provider_result.model,
                fallback_used=suggestion.provider_result.fallback_used,
                output_graph_json=workspace_to_graph(refreshed_workspace).model_dump(mode="json"),
            )
            self.session.commit()
            return IngestResponseData(job=ingest_job_to_read(job), graph=workspace_to_graph(refreshed_workspace))
        except Exception as exc:
            self.session.rollback()
            job = self.session.get(type(job), job.id) or job
            self.ingest_job_repository.mark_failed(job, error_message=str(exc))
            self.session.commit()
            raise

    def _resolve_project(self, project_id):
        if self.actor.source == "default":
            return self.project_repository.get_by_id(project_id)
        user = self.user_repository.get_or_create(email=self.actor.email, name=self.actor.name)
        return self.project_repository.get_for_user(project_id, user.id)
