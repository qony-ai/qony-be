from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.security import Actor
from app.repositories.projects import ProjectRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectDetail,
    ProjectListPayload,
    ProjectSummary,
    ProjectUpdateRequest,
    project_to_detail,
    project_to_summary,
)


class ProjectService:
    def __init__(self, *, session: Session, actor: Actor) -> None:
        self.session = session
        self.actor = actor
        self.user_repository = UserRepository(session)
        self.project_repository = ProjectRepository(session)
        self.workspace_repository = WorkspaceRepository(session)

    def list_projects(self) -> ProjectListPayload:
        if self.actor.source == "default":
            projects = self.project_repository.list_all()
        else:
            user = self.user_repository.get_or_create(email=self.actor.email, name=self.actor.name)
            projects = self.project_repository.list_for_user(user.id)
        return ProjectListPayload(items=[project_to_summary(project) for project in projects])

    def create_project(self, payload: ProjectCreateRequest) -> ProjectDetail:
        user = self.user_repository.get_or_create(email=self.actor.email, name=self.actor.name)
        project = self.project_repository.create(
            user_id=user.id,
            name=payload.name,
            description=payload.description,
            status=payload.status.value,
            metadata=payload.metadata,
        )
        self.workspace_repository.create_for_project(project_id=project.id, metadata={"created_by": self.actor.email})
        self.session.commit()
        refreshed = self.project_repository.get_for_user(project.id, user.id)
        if refreshed is None:
            raise NotFoundError("Created project could not be reloaded.")
        return project_to_detail(refreshed)

    def get_project(self, project_id) -> ProjectDetail:
        project = self._resolve_project(project_id)
        if project is None:
            raise NotFoundError("Project not found.")
        return project_to_detail(project)

    def update_project(self, project_id, payload: ProjectUpdateRequest) -> ProjectDetail:
        project = self._resolve_project(project_id)
        if project is None:
            raise NotFoundError("Project not found.")

        if payload.name is not None:
            project.name = payload.name
        if payload.description is not None:
            project.description = payload.description
        if payload.status is not None:
            project.status = payload.status.value
        if payload.metadata is not None:
            project.metadata_json = payload.metadata

        self.session.commit()
        refreshed = self.project_repository.get_by_id(project_id)
        if refreshed is None:
            raise NotFoundError("Updated project could not be reloaded.")
        return project_to_detail(refreshed)

    def delete_project(self, project_id) -> bool:
        project = self._resolve_project(project_id)
        if project is None:
            raise NotFoundError("Project not found.")
        self.project_repository.delete(project)
        self.session.commit()
        return True

    def _resolve_project(self, project_id):
        if self.actor.source == "default":
            return self.project_repository.get_by_id(project_id)
        user = self.user_repository.get_or_create(email=self.actor.email, name=self.actor.name)
        return self.project_repository.get_for_user(project_id, user.id)
