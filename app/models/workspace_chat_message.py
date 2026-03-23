from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class WorkspaceChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_chat_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_workspace_chat_messages_role_valid",
        ),
        CheckConstraint(
            "graph_version IS NULL OR graph_version >= 1",
            name="ck_workspace_chat_messages_graph_version_positive",
        ),
        Index(
            "ix_workspace_chat_messages_workspace_created_id",
            "workspace_id",
            "created_at",
            "id",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ai_request_log_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_request_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    graph_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_commands_json: Mapped[list[str]] = mapped_column(
        "applied_commands",
        JSON,
        default=list,
        nullable=False,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    project = relationship("Project", back_populates="workspace_chat_messages")
    workspace = relationship("Workspace", back_populates="chat_messages")
    user = relationship("User", back_populates="workspace_chat_messages")
    ai_request_log = relationship("AIRequestLog", back_populates="workspace_chat_messages")
