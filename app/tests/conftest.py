from __future__ import annotations

import base64
from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.base import Base
from app.main import create_app


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    database_path = tmp_path / "qony-test.db"
    return Settings(
        _env_file=None,
        environment="test",
        app_debug=False,
        database_url=f"sqlite:///{database_path}",
        ai_provider="stub",
        ai_fallback_to_stub=True,
        cors_origins=["http://localhost:3000"],
        internal_actor_secret="test-internal-actor-secret",
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


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


@pytest.fixture
def internal_actor_token(test_settings: Settings):
    def factory(
        *,
        sub: str = "auth-user-123",
        email: str = "tester@qony.ai",
        name: str = "Tester",
        plan: str = "free",
        entitlements: list[str] | None = None,
        exp: int | None = None,
        iss: str | None = None,
        aud: str | None = None,
    ) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "sub": sub,
            "email": email,
            "name": name,
            "plan": plan,
            "entitlements": entitlements or [],
            "iss": iss or test_settings.internal_actor_issuer,
            "aud": aud or test_settings.internal_actor_audience,
            "exp": exp or int(datetime.now(UTC).timestamp()) + 3600,
        }
        header_segment = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        payload_segment = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = hmac.new(
            test_settings.internal_actor_secret_value.encode("utf-8"),
            f"{header_segment}.{payload_segment}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return ".".join(
            [
                header_segment,
                payload_segment,
                _base64url_encode(signature),
            ]
        )

    return factory
