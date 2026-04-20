from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_auth_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")
    ingest_jobs = relationship("IngestJob", back_populates="requested_by_user")
    export_jobs = relationship("ExportJob", back_populates="requested_by_user")
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    usage_events = relationship("UsageEvent", back_populates="user", cascade="all, delete-orphan")
