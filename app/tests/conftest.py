from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.base import Base
from app.main import create_app
from app.schemas.workspace import GraphMetadata, GraphValidationSummary, WorkspaceGraph


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    database_path = tmp_path / "qony-test.db"
    return Settings(
        environment="test",
        app_debug=False,
        database_url=f"sqlite:///{database_path}",
        ai_provider="stub",
        ai_fallback_to_stub=True,
        cors_origins=["http://localhost:3000"],
    )


@pytest.fixture
def app(test_settings: Settings):
    application = create_app(test_settings)
    Base.metadata.create_all(bind=application.state.engine)
    yield application
    Base.metadata.drop_all(bind=application.state.engine)
    application.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def user_headers() -> dict[str, str]:
    return {
        "X-User-Email": "tester@qony.ai",
        "X-User-Name": "Tester",
    }


def make_empty_graph(*, project_id: UUID | None = None, workspace_id: UUID | None = None, version: int = 1) -> WorkspaceGraph:
    return WorkspaceGraph(
        nodes=[],
        edges=[],
        metadata=GraphMetadata(
            project_id=project_id or uuid4(),
            workspace_id=workspace_id or uuid4(),
            version=version,
            updated_at=datetime.now(UTC),
            validation=GraphValidationSummary(is_valid=True),
            attributes={},
        ),
    )
