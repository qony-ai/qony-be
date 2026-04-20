from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, get_settings
from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.repositories.users import UserRepository
from app.schemas.auth import AuthResponse, AuthTokens, AuthUserRead, LoginRequest, RefreshRequest, RegisterRequest
from app.schemas.common import ApiEnvelope
from app.utils.auth_utils import create_signed_token, decode_signed_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=ApiEnvelope[AuthResponse], status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ApiEnvelope[AuthResponse]:
    repository = UserRepository(session)
    existing = repository.get_by_email(str(payload.email))
    if existing is not None:
        raise ConflictError("A user with this email already exists.")
    user = repository.get_or_create(email=str(payload.email), name=payload.name)
    user.metadata_json = {**(user.metadata_json or {}), "password_hash": hash_password(payload.password)}
    session.commit()
    return ApiEnvelope(data=_auth_response_for_user(user, settings))


@router.post("/login", response_model=ApiEnvelope[AuthResponse])
async def login(
    payload: LoginRequest,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ApiEnvelope[AuthResponse]:
    repository = UserRepository(session)
    user = repository.get_by_email(str(payload.email))
    if user is None:
        raise AuthenticationError("Invalid email or password.")
    password_hash = str((user.metadata_json or {}).get("password_hash", ""))
    if not password_hash or not verify_password(payload.password, password_hash):
        raise AuthenticationError("Invalid email or password.")
    return ApiEnvelope(data=_auth_response_for_user(user, settings))


@router.post("/refresh", response_model=ApiEnvelope[AuthResponse])
async def refresh(
    payload: RefreshRequest,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ApiEnvelope[AuthResponse]:
    try:
        token_payload = decode_signed_token(payload.refresh_token, settings.internal_actor_secret_value)
    except Exception as exc:
        raise AuthenticationError("Refresh token is invalid.") from exc

    repository = UserRepository(session)
    user = repository.get_by_email(str(token_payload.get("email", "")))
    if user is None:
        raise AuthenticationError("Refresh token user is no longer available.")
    return ApiEnvelope(data=_auth_response_for_user(user, settings))


def _auth_response_for_user(user, settings: Settings) -> AuthResponse:
    base_payload = {
        "sub": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "iss": settings.internal_actor_issuer,
        "aud": settings.internal_actor_audience,
    }
    return AuthResponse(
        user=AuthUserRead(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            created_at=user.created_at,
            updated_at=user.updated_at,
        ),
        tokens=AuthTokens(
            access_token=create_signed_token(base_payload, settings.internal_actor_secret_value, expires_in_seconds=3600),
            refresh_token=create_signed_token(base_payload, settings.internal_actor_secret_value, expires_in_seconds=86400),
        ),
    )
