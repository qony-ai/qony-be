from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Edge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "edges"
    __table_args__ = (UniqueConstraint("workspace_id", "source_node_id", "target_node_id"),)

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    source_node_id: Mapped[UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    target_node_id: Mapped[UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    relation_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    workspace = relationship("Workspace", back_populates="edges")
    source_node = relationship("Node", foreign_keys=[source_node_id], back_populates="outgoing_edges")
    target_node = relationship("Node", foreign_keys=[target_node_id], back_populates="incoming_edges")
