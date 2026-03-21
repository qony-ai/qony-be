from dataclasses import dataclass

from fastapi import Request

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class Actor:
    email: str
    name: str
    source: str = "header_or_default"


def resolve_actor(request: Request, settings: Settings) -> Actor:
    email = request.headers.get("X-User-Email", settings.default_user_email).strip()
    name = request.headers.get("X-User-Name", settings.default_user_name).strip()
    source = "header" if "X-User-Email" in request.headers else "default"
    return Actor(email=email, name=name, source=source)

