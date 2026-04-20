from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, hashed_password: str) -> bool:
    return hmac.compare_digest(hash_password(password), hashed_password)


def create_signed_token(payload: dict[str, object], secret: str, *, expires_in_seconds: int = 3600) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    enriched_payload = {
        **payload,
        "exp": int((datetime.now(UTC) + timedelta(seconds=expires_in_seconds)).timestamp()),
    }
    header_segment = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_segment = _base64url_encode(json.dumps(enriched_payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        secret.encode("utf-8"),
        f"{header_segment}.{payload_segment}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return ".".join([header_segment, payload_segment, _base64url_encode(signature)])


def decode_signed_token(token: str, secret: str) -> dict[str, object]:
    header_segment, payload_segment, signature_segment = token.split(".")
    expected_signature = _base64url_encode(
        hmac.new(
            secret.encode("utf-8"),
            f"{header_segment}.{payload_segment}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
    )
    if not hmac.compare_digest(signature_segment, expected_signature):
        raise ValueError("Invalid signature")

    payload = json.loads(_base64url_decode(payload_segment))
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or datetime.now(UTC).timestamp() >= float(exp):
        raise ValueError("Token expired")
    return payload


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _base64url_decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("utf-8")).decode("utf-8")
