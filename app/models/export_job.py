from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ExportJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "export_jobs"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    export_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    output_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    slide_plan_json: Mapped[dict[str, Any]] = mapped_column("slide_plan", JSON, default=dict, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    project = relationship("Project", back_populates="export_jobs")
    workspace = relationship("Workspace", back_populates="export_jobs")
    requested_by_user = relationship("User", back_populates="export_jobs")
