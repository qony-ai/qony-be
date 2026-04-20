from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class UsageEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "usage_events"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    user = relationship("User", back_populates="usage_events")
    project = relationship("Project", back_populates="usage_events")
