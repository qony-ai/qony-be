from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json

from email_validator import EmailNotValidError, validate_email
from fastapi import Request

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, DomainValidationError


@dataclass(frozen=True, slots=True)
class Actor:
    auth_user_id: str | None
    email: str
    name: str
    plan: str = "free"
    entitlements: tuple[str, ...] = ()
    source: str = "header_or_default"


def resolve_actor(request: Request, settings: Settings) -> Actor:
    authorization = request.headers.get("Authorization")
    if authorization:
        return _resolve_actor_from_authorization_header(authorization, settings)

    if settings.allow_header_actor_fallback_effective:
        header_actor = _resolve_actor_from_headers(request, settings)
        if header_actor is not None:
            return header_actor

    if not settings.allow_default_actor_effective:
        raise AuthenticationError(
            "Actor authentication is required in this environment.",
            details={"accepted_methods": ["internal_bearer_token"]},
        )

    return Actor(
        auth_user_id=None,
        email=settings.default_user_email,
        name=settings.default_user_name,
        plan="free",
        entitlements=(),
        source="default",
    )


def _resolve_actor_from_authorization_header(
    authorization: str,
    settings: Settings,
) -> Actor:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("Authorization header must use Bearer authentication.")

    payload = _validate_internal_actor_token(token.strip(), settings)
    auth_user_id = payload.get("sub")
    if not isinstance(auth_user_id, str) or not auth_user_id.strip():
        raise AuthenticationError("Internal actor token is missing a valid subject.")

    return Actor(
        auth_user_id=auth_user_id.strip(),
        email=_normalize_actor_email(payload.get("email")),
        name=_normalize_actor_name(payload.get("name")),
        plan=_normalize_plan(payload.get("plan")),
        entitlements=_normalize_entitlements(payload.get("entitlements")),
        source="internal_token",
    )


def _resolve_actor_from_headers(request: Request, settings: Settings) -> Actor | None:
    email_header = settings.actor_email_header
    name_header = settings.actor_name_header
    raw_email = request.headers.get(email_header)
    raw_name = request.headers.get(name_header)

    if raw_email is None and raw_name is None:
        return None

    if raw_email is None or raw_name is None:
        raise AuthenticationError(
            "Both actor headers must be provided together.",
            details={"required_headers": [email_header, name_header]},
        )

    return Actor(
        auth_user_id=None,
        email=_normalize_actor_email(raw_email),
        name=_normalize_actor_name(raw_name),
        plan="free",
        entitlements=(),
        source="header",
    )


def _validate_internal_actor_token(token: str, settings: Settings) -> dict[str, object]:
    secret = settings.internal_actor_secret_value
    if not secret:
        raise AuthenticationError("Internal actor bearer validation is not configured.")

    try:
        header_segment, payload_segment, signature_segment = token.split(".")
    except ValueError as exc:
        raise AuthenticationError("Internal actor token is malformed.") from exc

    signed_value = f"{header_segment}.{payload_segment}".encode("utf-8")
    expected_signature = _base64url_encode(
        hmac.new(secret.encode("utf-8"), signed_value, hashlib.sha256).digest()
    )
    if not hmac.compare_digest(signature_segment, expected_signature):
        raise AuthenticationError("Internal actor token signature is invalid.")

    try:
        header = json.loads(_base64url_decode(header_segment))
        payload = json.loads(_base64url_decode(payload_segment))
    except (json.JSONDecodeError, ValueError) as exc:
        raise AuthenticationError("Internal actor token payload is invalid.") from exc

    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise AuthenticationError("Internal actor token must use HS256.")
    if not isinstance(payload, dict):
        raise AuthenticationError("Internal actor token payload must be a JSON object.")

    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or datetime.now(UTC).timestamp() >= float(exp):
        raise AuthenticationError("Internal actor token has expired.")

    issuer = payload.get("iss")
    if issuer is not None and issuer != settings.internal_actor_issuer:
        raise AuthenticationError("Internal actor token issuer is invalid.")

    audience = payload.get("aud")
    if isinstance(audience, str):
        audiences = [audience]
    elif isinstance(audience, list):
        audiences = [item for item in audience if isinstance(item, str)]
    else:
        audiences = []
    if settings.internal_actor_audience and settings.internal_actor_audience not in audiences:
        raise AuthenticationError("Internal actor token audience is invalid.")

    return payload


def _base64url_decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(f"{value}{padding}".encode("utf-8")).decode("utf-8")
    except Exception as exc:  # pragma: no cover
        raise ValueError("Invalid base64url value") from exc


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _normalize_actor_email(value: object) -> str:
    if not isinstance(value, str):
        raise DomainValidationError("Actor email must be a string.")

    email = value.strip()
    try:
        return validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise DomainValidationError("Actor email is invalid.") from exc


def _normalize_actor_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError("Actor name must not be empty.")
    return value.strip()


def _normalize_plan(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "free"
    return value.strip().lower()


def _normalize_entitlements(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise AuthenticationError("Internal actor token entitlements must be an array.")

    normalized = []
    for item in value:
        if isinstance(item, str) and item.strip():
            normalized.append(item.strip())

    return tuple(dict.fromkeys(normalized))
