from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_workspaces_version_positive"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    project = relationship("Project", back_populates="workspace")
    nodes = relationship("Node", back_populates="workspace", cascade="all, delete-orphan", order_by="Node.created_at")
    edges = relationship("Edge", back_populates="workspace", cascade="all, delete-orphan", order_by="Edge.created_at")
    ingest_jobs = relationship("IngestJob", back_populates="workspace")
    export_jobs = relationship("ExportJob", back_populates="workspace")
