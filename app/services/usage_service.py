from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import Actor
from app.domain.enums import UsageEventType
from app.models.usage_event import UsageEvent
from app.repositories.users import UserRepository


class UsageService:
    def __init__(self, *, session: Session, actor: Actor | None = None) -> None:
        self.session = session
        self.actor = actor
        self.user_repository = UserRepository(session)

    def record_event(
        self,
        *,
        event_type: UsageEventType,
        project_id,
        quantity: int = 1,
        metadata: dict | None = None,
    ) -> UsageEvent | None:
        if self.actor is None:
            return None
        user = self.user_repository.get_or_create(
            email=self.actor.email,
            name=self.actor.name,
            external_auth_id=self.actor.auth_user_id,
        )
        event = UsageEvent(
            user_id=user.id,
            project_id=project_id,
            event_type=event_type.value,
            quantity=quantity,
            metadata_json=metadata or {},
        )
        self.session.add(event)
        self.session.flush()
        return event

    def count_by_type(self, event_type: UsageEventType) -> int:
        statement = select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
            UsageEvent.event_type == event_type.value
        )
        return int(self.session.scalar(statement) or 0)
