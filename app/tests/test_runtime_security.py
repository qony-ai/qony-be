from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.base import Base
from app.main import create_app


def _build_client(settings: Settings) -> TestClient:
    app = create_app(settings)
    Base.metadata.create_all(bind=app.state.engine)
    return TestClient(app)


def test_production_environment_requires_actor_headers(tmp_path: Path) -> None:
    settings = Settings(
        environment="production",
        database_url=f"sqlite:///{tmp_path / 'prod-no-headers.db'}",
        ai_provider="stub",
        api_docs_enabled=False,
    )
    with _build_client(settings) as client:
        response = client.get("/api/v1/projects")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_actor_headers_must_be_provided_together(tmp_path: Path) -> None:
    settings = Settings(
        environment="production",
        database_url=f"sqlite:///{tmp_path / 'prod-partial-headers.db'}",
        ai_provider="stub",
    )
    with _build_client(settings) as client:
        response = client.get(
            "/api/v1/projects",
            headers={"X-User-Email": "tester@qony.ai"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_invalid_actor_email_is_rejected(tmp_path: Path) -> None:
    settings = Settings(
        environment="production",
        database_url=f"sqlite:///{tmp_path / 'prod-invalid-email.db'}",
        ai_provider="stub",
    )
    with _build_client(settings) as client:
        response = client.get(
            "/api/v1/projects",
            headers={
                "X-User-Email": "not-an-email",
                "X-User-Name": "Tester",
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "domain_validation_error"


def test_docs_can_be_disabled_in_production(tmp_path: Path) -> None:
    settings = Settings(
        environment="production",
        database_url=f"sqlite:///{tmp_path / 'prod-docs-disabled.db'}",
        ai_provider="stub",
        api_docs_enabled=False,
    )
    with _build_client(settings) as client:
        docs_response = client.get("/docs")
        openapi_response = client.get("/api/v1/openapi.json")

    assert docs_response.status_code == 404
    assert openapi_response.status_code == 404
