from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.workspace import Workspace


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
