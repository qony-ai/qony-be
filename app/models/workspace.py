from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    project = relationship("Project", back_populates="workspace")
    nodes = relationship("Node", back_populates="workspace", cascade="all, delete-orphan", order_by="Node.created_at")
    edges = relationship("Edge", back_populates="workspace", cascade="all, delete-orphan", order_by="Edge.created_at")
    ingest_jobs = relationship("IngestJob", back_populates="workspace")
    export_snapshots = relationship("ExportSnapshot", back_populates="workspace")
    ai_request_logs = relationship("AIRequestLog", back_populates="workspace")
    chat_messages = relationship(
        "WorkspaceChatMessage",
        back_populates="workspace",
        cascade="all, delete-orphan",
        order_by="WorkspaceChatMessage.created_at",
    )
