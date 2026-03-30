from __future__ import annotations

import base64
from datetime import UTC, datetime
import hashlib
import hmac
import json
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
        internal_actor_secret="runtime-security-secret",
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
        internal_actor_secret="runtime-security-secret",
        allow_header_actor_fallback=True,
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
        internal_actor_secret="runtime-security-secret",
        allow_header_actor_fallback=True,
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


def test_valid_internal_actor_token_is_accepted(tmp_path: Path) -> None:
    settings = Settings(
        environment="production",
        database_url=f"sqlite:///{tmp_path / 'prod-bearer.db'}",
        ai_provider="stub",
        internal_actor_secret="runtime-security-secret",
    )
    with _build_client(settings) as client:
        token = _build_internal_token(
            secret=settings.internal_actor_secret_value,
            issuer=settings.internal_actor_issuer,
            audience=settings.internal_actor_audience,
        )
        response = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["data"]["items"] == []


def test_invalid_internal_actor_token_is_rejected_without_header_fallback(tmp_path: Path) -> None:
    settings = Settings(
        environment="production",
        database_url=f"sqlite:///{tmp_path / 'prod-invalid-bearer.db'}",
        ai_provider="stub",
        internal_actor_secret="runtime-security-secret",
        allow_header_actor_fallback=True,
    )
    with _build_client(settings) as client:
        response = client.get(
            "/api/v1/projects",
            headers={
                "Authorization": "Bearer invalid.token.value",
                "X-User-Email": "tester@qony.ai",
                "X-User-Name": "Tester",
            },
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


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


def _build_internal_token(
    *,
    secret: str,
    issuer: str,
    audience: str,
    sub: str = "auth-user-123",
    email: str = "tester@qony.ai",
    name: str = "Tester",
) -> str:
    def encode(value: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode("utf-8")
        ).decode("utf-8").rstrip("=")

    header_segment = encode({"alg": "HS256", "typ": "JWT"})
    payload_segment = encode(
        {
            "sub": sub,
            "email": email,
            "name": name,
            "plan": "free",
            "entitlements": [],
            "iss": issuer,
            "aud": audience,
            "exp": int(datetime.now(UTC).timestamp()) + 3600,
        }
    )
    signature = hmac.new(
        secret.encode("utf-8"),
        f"{header_segment}.{payload_segment}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return ".".join(
        [
            header_segment,
            payload_segment,
            base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("="),
        ]
    )
