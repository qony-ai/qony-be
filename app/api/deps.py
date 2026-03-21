from collections.abc import Generator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import Actor, resolve_actor
from app.services.ai_service import AIService
from app.services.export_service import ExportPreviewService
from app.services.ingest_service import IngestService
from app.services.project_service import ProjectService
from app.services.workspace_service import WorkspaceService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db_session(request: Request) -> Generator[Session, None, None]:
    session_factory = request.app.state.session_factory
    session: Session = session_factory()
    try:
        yield session
    finally:
        session.close()


def get_actor(request: Request, settings: Settings = Depends(get_settings)) -> Actor:
    return resolve_actor(request=request, settings=settings)


def get_project_service(
    session: Session = Depends(get_db_session),
    actor: Actor = Depends(get_actor),
) -> ProjectService:
    return ProjectService(session=session, actor=actor)


def get_ai_service(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(get_actor),
) -> AIService:
    return AIService(session=session, settings=settings, actor=actor)


def get_ingest_service(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(get_actor),
) -> IngestService:
    return IngestService(session=session, settings=settings, actor=actor)


def get_workspace_service(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(get_actor),
) -> WorkspaceService:
    return WorkspaceService(session=session, settings=settings, actor=actor)


def get_export_service(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(get_actor),
) -> ExportPreviewService:
    return ExportPreviewService(session=session, settings=settings, actor=actor)

