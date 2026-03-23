from email_validator import EmailNotValidError, validate_email
from dataclasses import dataclass

from fastapi import Request

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, DomainValidationError


@dataclass(frozen=True, slots=True)
class Actor:
    email: str
    name: str
    source: str = "header_or_default"


def resolve_actor(request: Request, settings: Settings) -> Actor:
    email_header = settings.actor_email_header
    name_header = settings.actor_name_header
    raw_email = request.headers.get(email_header)
    raw_name = request.headers.get(name_header)

    if raw_email is None and raw_name is None:
        if not settings.allow_default_actor_effective:
            raise AuthenticationError(
                "Actor headers are required in this environment.",
                details={"required_headers": [email_header, name_header]},
            )
        return Actor(
            email=settings.default_user_email,
            name=settings.default_user_name,
            source="default",
        )

    if raw_email is None or raw_name is None:
        raise AuthenticationError(
            "Both actor headers must be provided together.",
            details={"required_headers": [email_header, name_header]},
        )

    email = raw_email.strip()
    name = raw_name.strip()
    if not name:
        raise DomainValidationError("Actor name header must not be empty.")
    try:
        normalized_email = validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise DomainValidationError("Actor email header is invalid.") from exc
    return Actor(email=normalized_email, name=name, source="header")
