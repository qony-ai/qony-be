from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import ProjectStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default=ProjectStatus.DRAFT.value, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    user = relationship("User", back_populates="projects")
    workspace = relationship(
        "Workspace",
        back_populates="project",
        uselist=False,
        cascade="all, delete-orphan",
    )
    ingest_jobs = relationship("IngestJob", back_populates="project", cascade="all, delete-orphan")
    export_snapshots = relationship("ExportSnapshot", back_populates="project", cascade="all, delete-orphan")
    ai_request_logs = relationship("AIRequestLog", back_populates="project", cascade="all, delete-orphan")
    workspace_chat_messages = relationship(
        "WorkspaceChatMessage",
        back_populates="project",
        cascade="all, delete-orphan",
    )
