from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.core.security import Actor
from app.domain.export import build_export_preview
from app.repositories.export_snapshots import ExportSnapshotRepository
from app.repositories.projects import ProjectRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository
from app.schemas.export import ExportPreviewPayload, export_snapshot_to_read
from app.services.graph_mapper import workspace_to_graph


class ExportPreviewService:
    def __init__(self, *, session: Session, settings: Settings, actor: Actor) -> None:
        self.session = session
        self.settings = settings
        self.actor = actor
        self.user_repository = UserRepository(session)
        self.project_repository = ProjectRepository(session)
        self.workspace_repository = WorkspaceRepository(session)
        self.export_snapshot_repository = ExportSnapshotRepository(session)

    def build_preview(self, project_id) -> ExportPreviewPayload:
        user = self.user_repository.get_or_create(email=self.actor.email, name=self.actor.name)
        project = self._resolve_project(project_id)
        if project is None:
            raise NotFoundError("Project not found.")
        workspace = self.workspace_repository.get_by_project_id(project.id)
        if workspace is None:
            raise NotFoundError("Workspace not found.")
        graph = workspace_to_graph(workspace)
        chains, warnings = build_export_preview(graph)
        output = {
            "chains": [chain.model_dump(mode="json") for chain in chains],
            "warnings": warnings,
        }
        snapshot = self.export_snapshot_repository.create_snapshot(
            project_id=project.id,
            workspace_id=workspace.id,
            requested_by_user_id=user.id,
            branch_count=len(chains),
            output_json=output,
        )
        self.session.commit()
        return export_snapshot_to_read(snapshot)

    def _resolve_project(self, project_id):
        if self.actor.source == "default":
            return self.project_repository.get_by_id(project_id)
        user = self.user_repository.get_or_create(email=self.actor.email, name=self.actor.name)
        return self.project_repository.get_for_user(project_id, user.id)
