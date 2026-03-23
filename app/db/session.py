from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


def create_engine_from_settings(settings: Settings | None = None) -> Engine:
    active_settings = settings or get_settings()
    is_sqlite = active_settings.database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine_kwargs: dict[str, object] = {
        "echo": active_settings.database_echo,
        "pool_pre_ping": True,
        "connect_args": connect_args,
    }
    if not is_sqlite:
        engine_kwargs.update(
            {
                "pool_size": active_settings.database_pool_size,
                "max_overflow": active_settings.database_max_overflow,
                "pool_timeout": active_settings.database_pool_timeout_seconds,
                "pool_recycle": active_settings.database_pool_recycle_seconds,
                "pool_use_lifo": True,
            }
        )
    return create_engine(active_settings.database_url, **engine_kwargs)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
