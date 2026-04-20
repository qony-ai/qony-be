"""Flatten graph model: drop NodeRank, add typed nodes/edges with web-enrichment fields.

Spec: resources/NODE_TYPES.md, resources/CONVENTIONS.md.

This migration is destructive for existing node/edge rows (dev-only data).
The old Minto/MECE rank 1-6 model is replaced by a flat typed graph.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260321_0004"
down_revision = "20260321_0003"
branch_labels = None
depends_on = None


NODE_TYPES = (
    "problem", "solution", "assumption", "metric", "stakeholder",
    "risk", "opportunity", "constraint", "evidence", "market_data",
    "trend", "competitor", "regulation", "objective", "resource",
)

EDGE_TYPES = (
    "causes", "supports", "contradicts", "requires",
    "affects", "related_to", "measured_by", "mitigated_by",
)

NODE_SOURCES = ("document", "web", "user")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    # Destructive: clear existing rows before applying the new constraints.
    # Existing edges/nodes were modelled around rank 1-6; they cannot survive the new schema.
    op.execute("DELETE FROM edges")
    op.execute("DELETE FROM nodes")

    # --- nodes: drop rank-era columns/constraints/indexes ---
    op.drop_constraint("ck_nodes_rank_valid", "nodes", type_="check")
    op.drop_index("ix_nodes_workspace_id_rank", table_name="nodes")
    op.drop_column("nodes", "rank")
    op.drop_column("nodes", "content")

    # --- nodes: add flat-graph columns ---
    op.add_column(
        "nodes",
        sa.Column("type", sa.String(length=30), nullable=False),
    )
    op.add_column(
        "nodes",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )
    # Remove the default once the column is in place; spec requires explicit description.
    op.alter_column("nodes", "description", server_default=None)

    op.add_column(
        "nodes",
        sa.Column(
            "is_enrichment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("nodes", sa.Column("source_url", sa.Text(), nullable=True))
    op.add_column(
        "nodes",
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
    )

    # Old default was 'manual'; flat graph uses 'document' as the extraction default.
    op.alter_column(
        "nodes",
        "source",
        existing_type=sa.String(length=32),
        server_default="document",
    )

    op.create_check_constraint(
        "ck_nodes_type_valid",
        "nodes",
        _in_list("type", NODE_TYPES),
    )
    op.create_check_constraint(
        "ck_nodes_source_valid",
        "nodes",
        _in_list("source", NODE_SOURCES),
    )
    op.create_check_constraint(
        "ck_nodes_confidence_range",
        "nodes",
        "confidence >= 0.0 AND confidence <= 1.0",
    )
    # Web-enrichment invariant: is_enrichment is true iff source='web', and web nodes need a URL.
    op.create_check_constraint(
        "ck_nodes_web_enrichment_consistent",
        "nodes",
        "(source = 'web' AND is_enrichment = true AND source_url IS NOT NULL) "
        "OR (source <> 'web' AND is_enrichment = false)",
    )

    op.create_index(
        "ix_nodes_workspace_id_type",
        "nodes",
        ["workspace_id", "type"],
        unique=False,
    )
    op.create_index("ix_nodes_source", "nodes", ["source"], unique=False)

    # --- edges: add relation type ---
    op.add_column(
        "edges",
        sa.Column(
            "type",
            sa.String(length=30),
            nullable=False,
            server_default="related_to",
        ),
    )
    op.alter_column("edges", "type", server_default=None)

    op.create_check_constraint(
        "ck_edges_type_valid",
        "edges",
        _in_list("type", EDGE_TYPES),
    )
    op.create_index("ix_edges_type", "edges", ["type"], unique=False)


def downgrade() -> None:
    # Reverse of upgrade. Destructive: existing flat-graph rows dropped.
    op.execute("DELETE FROM edges")
    op.execute("DELETE FROM nodes")

    op.drop_index("ix_edges_type", table_name="edges")
    op.drop_constraint("ck_edges_type_valid", "edges", type_="check")
    op.drop_column("edges", "type")

    op.drop_index("ix_nodes_source", table_name="nodes")
    op.drop_index("ix_nodes_workspace_id_type", table_name="nodes")
    op.drop_constraint("ck_nodes_web_enrichment_consistent", "nodes", type_="check")
    op.drop_constraint("ck_nodes_confidence_range", "nodes", type_="check")
    op.drop_constraint("ck_nodes_source_valid", "nodes", type_="check")
    op.drop_constraint("ck_nodes_type_valid", "nodes", type_="check")

    op.alter_column(
        "nodes",
        "source",
        existing_type=sa.String(length=32),
        server_default="manual",
    )

    op.drop_column("nodes", "confidence")
    op.drop_column("nodes", "source_url")
    op.drop_column("nodes", "is_enrichment")
    op.drop_column("nodes", "description")
    op.drop_column("nodes", "type")

    op.add_column("nodes", sa.Column("content", sa.Text(), nullable=True))
    op.add_column(
        "nodes",
        sa.Column(
            "rank",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.alter_column("nodes", "rank", server_default=None)
    op.create_index(
        "ix_nodes_workspace_id_rank",
        "nodes",
        ["workspace_id", "rank"],
        unique=False,
    )
    op.create_check_constraint(
        "ck_nodes_rank_valid",
        "nodes",
        "rank BETWEEN 1 AND 6",
    )
