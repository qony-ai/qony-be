from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

NODE_TYPE_VALUES = (
    "problem", "solution", "assumption", "metric", "stakeholder",
    "risk", "opportunity", "constraint", "evidence", "market_data",
    "trend", "competitor", "regulation", "objective", "resource",
)

NODE_SOURCE_VALUES = ("document", "web", "user")

_NODE_TYPE_SQL = "type IN (" + ", ".join(f"'{v}'" for v in NODE_TYPE_VALUES) + ")"
_NODE_SOURCE_SQL = "source IN (" + ", ".join(f"'{v}'" for v in NODE_SOURCE_VALUES) + ")"


class Node(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "nodes"
    __table_args__ = (
        CheckConstraint(_NODE_TYPE_SQL, name="ck_nodes_type_valid"),
        CheckConstraint(_NODE_SOURCE_SQL, name="ck_nodes_source_valid"),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_nodes_confidence_range",
        ),
        CheckConstraint(
            "(source = 'web' AND is_enrichment = true AND source_url IS NOT NULL) "
            "OR (source <> 'web' AND is_enrichment = false)",
            name="ck_nodes_web_enrichment_consistent",
        ),
        Index("ix_nodes_workspace_id_type", "workspace_id", "type"),
        Index("ix_nodes_source", "source"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="document")
    is_enrichment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    position_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    position_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )

    workspace = relationship("Workspace", back_populates="nodes")
    outgoing_edges = relationship(
        "Edge", foreign_keys="Edge.source_node_id", back_populates="source_node"
    )
    incoming_edges = relationship(
        "Edge", foreign_keys="Edge.target_node_id", back_populates="target_node"
    )
