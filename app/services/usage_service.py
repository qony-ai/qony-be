"""Plan-tier metering and limit enforcement.

Responsibilities:

* :meth:`UsageService.record_event` — append a :class:`UsageEvent` row for
  a metered action (AI call, export job, document upload, web enrichment).
* :meth:`UsageService.monthly_usage` — aggregate quantity per event type
  for the current calendar month.
* :meth:`UsageService.check_limit` — raise :class:`LimitExceededError`
  when the caller has exhausted their plan's quota. Enterprise tier has
  ``None`` quota (unmetered).

The plan tier is read from ``user.metadata_json['plan_tier']`` during
Phase 1; Phase 2 moves it onto a proper billing column.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.limits import DEFAULT_TIER, PlanTier, UsageLimits, get_limits
from app.core.security import Actor
from app.models.usage_event import UsageEvent
from app.models.user import User
from app.repositories.users import UserRepository

UsageEventType = Literal["ai_call", "export_job", "document_upload", "web_enrichment"]

_LIMIT_KEY_FOR_EVENT: dict[UsageEventType, str] = {
    "ai_call": "ai_calls_per_month",
    "export_job": "exports_per_month",
    "document_upload": "document_uploads_per_month",
}


class LimitExceededError(AppError):
    def __init__(
        self,
        *,
        event_type: UsageEventType,
        tier: PlanTier,
        limit: int,
        current: int,
    ) -> None:
        super().__init__(
            code="usage_limit_exceeded",
            message=f"Monthly {event_type} limit reached for the {tier} plan.",
            status_code=429,
            details={
                "event_type": event_type,
                "plan_tier": tier,
                "limit": limit,
                "current": current,
            },
        )


class UsageService:
    def __init__(self, *, session: Session, settings: Settings, actor: Actor) -> None:
        self.session = session
        self.settings = settings
        self.actor = actor
        self.user_repository = UserRepository(session)

    # ------------------------------------------------------------- recording

    def record_event(
        self,
        *,
        event_type: UsageEventType,
        project_id: UUID | None = None,
        quantity: int = 1,
        metadata: dict | None = None,
    ) -> UsageEvent:
        user = self._current_user()
        event = UsageEvent(
            user_id=user.id,
            project_id=project_id,
            event_type=event_type,
            quantity=quantity,
            metadata_json=metadata or {},
        )
        self.session.add(event)
        self.session.flush()
        return event

    # ------------------------------------------------------------ aggregates

    def monthly_usage(self, *, user_id: UUID, now: datetime | None = None) -> dict[str, int]:
        month_start = _month_start(now or datetime.now(UTC))
        stmt = (
            select(UsageEvent.event_type, func.coalesce(func.sum(UsageEvent.quantity), 0))
            .where(UsageEvent.user_id == user_id)
            .where(UsageEvent.created_at >= month_start)
            .group_by(UsageEvent.event_type)
        )
        return {event_type: int(total) for event_type, total in self.session.execute(stmt).all()}

    # --------------------------------------------------------------- limits

    def check_limit(
        self,
        *,
        event_type: UsageEventType,
        now: datetime | None = None,
    ) -> None:
        """Raise if recording one more unit of ``event_type`` would exceed the plan limit.

        Safe to call immediately before :meth:`record_event`. Events not
        enumerated in :data:`_LIMIT_KEY_FOR_EVENT` (e.g. ``web_enrichment``
        today) are untracked and pass through.
        """

        limit_key = _LIMIT_KEY_FOR_EVENT.get(event_type)
        if limit_key is None:
            return
        user = self._current_user()
        tier = self._resolve_tier(user)
        limits: UsageLimits = get_limits(tier)
        limit = limits.get(limit_key)  # type: ignore[assignment]
        if limit is None:
            return
        current = self.monthly_usage(user_id=user.id, now=now).get(event_type, 0)
        if current >= limit:
            raise LimitExceededError(
                event_type=event_type,
                tier=tier,
                limit=limit,
                current=current,
            )

    # ----------------------------------------------------------------- utils

    def _current_user(self) -> User:
        return self.user_repository.get_or_create(
            email=self.actor.email,
            name=self.actor.name,
            external_auth_id=self.actor.auth_user_id,
        )

    def _resolve_tier(self, user: User) -> PlanTier:
        tier = (user.metadata_json or {}).get("plan_tier")
        if tier in ("free", "pro", "enterprise"):
            return tier  # type: ignore[return-value]
        return DEFAULT_TIER


def _month_start(reference: datetime) -> datetime:
    return reference.astimezone(UTC).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
