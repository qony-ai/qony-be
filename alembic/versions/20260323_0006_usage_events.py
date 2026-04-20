"""Add usage_events table for plan-tier metering.

Records metered actions — AI calls, export jobs, document uploads, and
web enrichment hits — so :mod:`app.services.usage_service` can enforce
per-month limits defined in :mod:`app.core.limits`.

Scope note: this lays the schema for Phase 2 metering. The initial
rollout only records events; admin UI + Midtrans billing integration
arrive in later chunks.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_0006"
down_revision = "20260322_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('ai_call', 'export_job', 'document_upload', 'web_enrichment')",
            name="ck_usage_events_type_valid",
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_usage_events_quantity_nonnegative"),
    )
    op.create_index("ix_usage_events_user_id", "usage_events", ["user_id"], unique=False)
    op.create_index(
        "ix_usage_events_project_id", "usage_events", ["project_id"], unique=False
    )
    op.create_index(
        "ix_usage_events_event_type", "usage_events", ["event_type"], unique=False
    )
    op.create_index(
        "ix_usage_events_user_id_created_at",
        "usage_events",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_usage_events_user_id_created_at", table_name="usage_events")
    op.drop_index("ix_usage_events_event_type", table_name="usage_events")
    op.drop_index("ix_usage_events_project_id", table_name="usage_events")
    op.drop_index("ix_usage_events_user_id", table_name="usage_events")
    op.drop_table("usage_events")
