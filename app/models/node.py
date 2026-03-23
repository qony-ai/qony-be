from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Node(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "nodes"
    __table_args__ = (
        CheckConstraint("rank BETWEEN 1 AND 6", name="ck_nodes_rank_valid"),
        Index("ix_nodes_workspace_id_rank", "workspace_id", "rank"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    position_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    position_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    workspace = relationship("Workspace", back_populates="nodes")
    outgoing_edges = relationship("Edge", foreign_keys="Edge.source_node_id", back_populates="source_node")
    incoming_edges = relationship("Edge", foreign_keys="Edge.target_node_id", back_populates="target_node")
