from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_db_session, get_settings
from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
        "ai_provider": settings.ai_provider,
    }


@router.get("/ready")
def ready(
    request: Request,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise ServiceUnavailableError("Database readiness check failed.") from exc
    return {
        "status": "ready",
        "database": "ok",
        "ai_provider": settings.ai_provider,
        "request_id": getattr(request.state, "request_id", None),
    }
