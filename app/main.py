from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import register_exception_handlers
from app.api.middleware import register_middleware
from app.api.routes import export, health, ingest, projects, workspace
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import create_engine_from_settings, create_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    configure_logging(active_settings)

    app = FastAPI(
        title=active_settings.app_name,
        debug=active_settings.app_debug,
        docs_url="/docs" if active_settings.docs_enabled else None,
        redoc_url="/redoc" if active_settings.docs_enabled else None,
        openapi_url=f"{active_settings.api_prefix}/openapi.json" if active_settings.docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = active_settings
    app.state.engine = create_engine_from_settings(active_settings)
    app.state.session_factory = create_session_factory(app.state.engine)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[active_settings.request_id_header],
    )

    register_middleware(app)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(projects.router, prefix=active_settings.api_prefix)
    app.include_router(ingest.router, prefix=active_settings.api_prefix)
    app.include_router(workspace.router, prefix=active_settings.api_prefix)
    app.include_router(export.router, prefix=active_settings.api_prefix)

    return app


app = create_app()
