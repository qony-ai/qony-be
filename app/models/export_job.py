from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


DELIVERABLE_TYPES = ("pitch_deck", "business_document")
EXPORT_JOB_STATUSES = ("pending", "planning", "rendering", "completed", "failed")


class ExportJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "export_jobs"
    __table_args__ = (
        CheckConstraint(
            "deliverable_type IN ('pitch_deck', 'business_document')",
            name="ck_export_jobs_deliverable_type_valid",
        ),
        CheckConstraint(
            "status IN ('pending', 'planning', 'rendering', 'completed', 'failed')",
            name="ck_export_jobs_status_valid",
        ),
        CheckConstraint(
            "graph_version_at_request IS NULL OR graph_version_at_request >= 1",
            name="ck_export_jobs_graph_version_positive",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    deliverable_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    graph_version_at_request: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manifest_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    slide_plan_json: Mapped[dict[str, Any]] = mapped_column(
        "slide_plan", JSON, default=dict, nullable=False
    )
    warnings_json: Mapped[list[Any]] = mapped_column(
        "warnings", JSON, default=list, nullable=False
    )
    html_artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    project = relationship("Project", back_populates="export_jobs")
    workspace = relationship("Workspace", back_populates="export_jobs")
    requested_by_user = relationship("User", back_populates="export_jobs")
