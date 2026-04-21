"""Repair local export_jobs drift to the current engine schema.

Some development databases already contain an older ``export_jobs``
table shape (``export_type``, ``output_url``, ``metadata``) while the
current backend expects the library-export schema introduced in
``20260322_0005``. Because ``export_jobs`` only stores derived export
artifacts, this repair migration rebuilds the table to the canonical
shape used by the running code.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260421_0007"
down_revision = "20260323_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS export_jobs CASCADE")

    op.create_table(
        "export_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("deliverable_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("graph_version_at_request", sa.Integer(), nullable=True),
        sa.Column("manifest_version", sa.String(length=64), nullable=True),
        sa.Column("slide_plan", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("html_artifact_path", sa.Text(), nullable=True),
        sa.Column("pdf_artifact_path", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "deliverable_type IN ('pitch_deck', 'business_document')",
            name="ck_export_jobs_deliverable_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'planning', 'rendering', 'completed', 'failed')",
            name="ck_export_jobs_status_valid",
        ),
        sa.CheckConstraint(
            "graph_version_at_request IS NULL OR graph_version_at_request >= 1",
            name="ck_export_jobs_graph_version_positive",
        ),
    )
    op.create_index("ix_export_jobs_project_id", "export_jobs", ["project_id"], unique=False)
    op.create_index("ix_export_jobs_workspace_id", "export_jobs", ["workspace_id"], unique=False)
    op.create_index(
        "ix_export_jobs_requested_by_user_id",
        "export_jobs",
        ["requested_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_export_jobs_status_created_at",
        "export_jobs",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    pass
