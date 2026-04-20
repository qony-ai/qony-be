from collections.abc import Generator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import Actor, resolve_actor
from app.services.admin_service import AdminService
from app.services.export_engine import ExportEngine
from app.services.ingest_service import PRDIngestionService
from app.services.graph_engine import GraphEngine
from app.services.payment_service import PaymentService
from app.services.project_service import ProjectService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db_session(request: Request) -> Generator[Session, None, None]:
    session_factory = request.app.state.session_factory
    session: Session = session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_actor(request: Request, settings: Settings = Depends(get_settings)) -> Actor:
    return resolve_actor(request=request, settings=settings)


def get_project_service(
    session: Session = Depends(get_db_session),
    actor: Actor = Depends(get_actor),
) -> ProjectService:
    return ProjectService(session=session, actor=actor)


def get_prd_ingestion_service(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(get_actor),
) -> PRDIngestionService:
    return PRDIngestionService(session=session, settings=settings, actor=actor)


def get_graph_engine(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(get_actor),
) -> GraphEngine:
    return GraphEngine(session=session, settings=settings, actor=actor)


def get_export_engine(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(get_actor),
) -> ExportEngine:
    return ExportEngine(session=session, settings=settings, actor=actor)


def get_payment_service(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(get_actor),
) -> PaymentService:
    return PaymentService(session=session, settings=settings, actor=actor)


def get_admin_service(
    session: Session = Depends(get_db_session),
    actor: Actor = Depends(get_actor),
) -> AdminService:
    return AdminService(session=session, actor=actor)
