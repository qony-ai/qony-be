from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ExportSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "export_snapshots"
    __table_args__ = (
        CheckConstraint(
            "branch_count >= 0",
            name="ck_export_snapshots_branch_count_nonnegative",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    branch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_json: Mapped[dict[str, Any]] = mapped_column("output", JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    project = relationship("Project", back_populates="export_snapshots")
    workspace = relationship("Workspace", back_populates="export_snapshots")
    requested_by_user = relationship("User", back_populates="export_snapshots")
