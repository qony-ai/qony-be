"""Add workspace chat messages."""

from alembic import op
import sqlalchemy as sa


revision = "20260321_0002"
down_revision = "20260321_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_chat_messages",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("ai_request_log_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("graph_version", sa.Integer(), nullable=True),
        sa.Column("applied_commands", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ai_request_log_id"],
            ["ai_request_logs.id"],
            name=op.f("fk_workspace_chat_messages_ai_request_log_id_ai_request_logs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_workspace_chat_messages_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_workspace_chat_messages_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_chat_messages_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_chat_messages")),
    )
    op.create_index(
        op.f("ix_workspace_chat_messages_project_id"),
        "workspace_chat_messages",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_chat_messages_workspace_id"),
        "workspace_chat_messages",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_chat_messages_user_id"),
        "workspace_chat_messages",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_chat_messages_ai_request_log_id"),
        "workspace_chat_messages",
        ["ai_request_log_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_workspace_chat_messages_ai_request_log_id"), table_name="workspace_chat_messages")
    op.drop_index(op.f("ix_workspace_chat_messages_user_id"), table_name="workspace_chat_messages")
    op.drop_index(op.f("ix_workspace_chat_messages_workspace_id"), table_name="workspace_chat_messages")
    op.drop_index(op.f("ix_workspace_chat_messages_project_id"), table_name="workspace_chat_messages")
    op.drop_table("workspace_chat_messages")
