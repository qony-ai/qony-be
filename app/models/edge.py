from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

EDGE_TYPE_VALUES = (
    "causes", "supports", "contradicts", "requires",
    "affects", "related_to", "measured_by", "mitigated_by",
)

_EDGE_TYPE_SQL = "type IN (" + ", ".join(f"'{v}'" for v in EDGE_TYPE_VALUES) + ")"


class Edge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "edges"
    __table_args__ = (
        UniqueConstraint("workspace_id", "source_node_id", "target_node_id"),
        CheckConstraint(_EDGE_TYPE_SQL, name="ck_edges_type_valid"),
        Index("ix_edges_type", "type"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_node_id: Mapped[UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_node_id: Mapped[UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    # `label` is a freeform human annotation on the relation; the queryable semantic is `type`.
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )

    workspace = relationship("Workspace", back_populates="edges")
    source_node = relationship(
        "Node", foreign_keys=[source_node_id], back_populates="outgoing_edges"
    )
    target_node = relationship(
        "Node", foreign_keys=[target_node_id], back_populates="incoming_edges"
    )
