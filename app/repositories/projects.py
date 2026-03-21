from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.project import Project


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_user(self, user_id: UUID) -> list[Project]:
        statement = (
            select(Project)
            .options(joinedload(Project.user), selectinload(Project.workspace))
            .where(Project.user_id == user_id)
            .order_by(Project.updated_at.desc())
        )
        return list(self.session.scalars(statement).unique())

    def list_all(self) -> list[Project]:
        statement = (
            select(Project)
            .options(joinedload(Project.user), selectinload(Project.workspace))
            .order_by(Project.updated_at.desc())
        )
        return list(self.session.scalars(statement).unique())

    def get_for_user(self, project_id: UUID, user_id: UUID) -> Project | None:
        statement = (
            select(Project)
            .options(joinedload(Project.user), selectinload(Project.workspace))
            .where(Project.id == project_id, Project.user_id == user_id)
        )
        return self.session.scalar(statement)

    def get_by_id(self, project_id: UUID) -> Project | None:
        statement = (
            select(Project)
            .options(joinedload(Project.user), selectinload(Project.workspace))
            .where(Project.id == project_id)
        )
        return self.session.scalar(statement)

    def create(
        self,
        *,
        user_id: UUID,
        name: str,
        description: str | None,
        status: str,
        metadata: dict,
    ) -> Project:
        project = Project(
            user_id=user_id,
            name=name,
            description=description,
            status=status,
            metadata_json=metadata,
        )
        self.session.add(project)
        self.session.flush()
        return project

    def delete(self, project: Project) -> None:
        self.session.delete(project)
