"""Harden schema constraints and indexes."""

from alembic import op


revision = "20260321_0003"
down_revision = "20260321_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_projects_user_id"), table_name="projects")
    op.drop_index(op.f("ix_workspaces_project_id"), table_name="workspaces")
    op.drop_index(op.f("ix_nodes_workspace_id"), table_name="nodes")
    op.drop_index(op.f("ix_workspace_chat_messages_workspace_id"), table_name="workspace_chat_messages")

    op.create_index(
        "ix_projects_user_id_updated_at",
        "projects",
        ["user_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_projects_updated_at",
        "projects",
        ["updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_nodes_workspace_id_rank",
        "nodes",
        ["workspace_id", "rank"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ingest_jobs_requested_by_user_id"),
        "ingest_jobs",
        ["requested_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_export_snapshots_requested_by_user_id"),
        "export_snapshots",
        ["requested_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_chat_messages_workspace_created_id",
        "workspace_chat_messages",
        ["workspace_id", "created_at", "id"],
        unique=False,
    )

    op.create_check_constraint(
        "ck_projects_name_nonempty",
        "projects",
        "length(trim(name)) > 0",
    )
    op.create_check_constraint(
        "ck_projects_status_valid",
        "projects",
        "status IN ('draft', 'active', 'archived')",
    )
    op.create_check_constraint(
        "ck_workspaces_version_positive",
        "workspaces",
        "version >= 1",
    )
    op.create_check_constraint(
        "ck_nodes_rank_valid",
        "nodes",
        "rank BETWEEN 1 AND 6",
    )
    op.create_check_constraint(
        "ck_ai_request_logs_latency_nonnegative",
        "ai_request_logs",
        "latency_ms IS NULL OR latency_ms >= 0",
    )
    op.create_check_constraint(
        "ck_export_snapshots_branch_count_nonnegative",
        "export_snapshots",
        "branch_count >= 0",
    )
    op.create_check_constraint(
        "ck_workspace_chat_messages_role_valid",
        "workspace_chat_messages",
        "role IN ('user', 'assistant')",
    )
    op.create_check_constraint(
        "ck_workspace_chat_messages_graph_version_positive",
        "workspace_chat_messages",
        "graph_version IS NULL OR graph_version >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_workspace_chat_messages_graph_version_positive",
        "workspace_chat_messages",
        type_="check",
    )
    op.drop_constraint(
        "ck_workspace_chat_messages_role_valid",
        "workspace_chat_messages",
        type_="check",
    )
    op.drop_constraint(
        "ck_export_snapshots_branch_count_nonnegative",
        "export_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_ai_request_logs_latency_nonnegative",
        "ai_request_logs",
        type_="check",
    )
    op.drop_constraint(
        "ck_nodes_rank_valid",
        "nodes",
        type_="check",
    )
    op.drop_constraint(
        "ck_workspaces_version_positive",
        "workspaces",
        type_="check",
    )
    op.drop_constraint(
        "ck_projects_status_valid",
        "projects",
        type_="check",
    )
    op.drop_constraint(
        "ck_projects_name_nonempty",
        "projects",
        type_="check",
    )

    op.drop_index("ix_workspace_chat_messages_workspace_created_id", table_name="workspace_chat_messages")
    op.drop_index(op.f("ix_export_snapshots_requested_by_user_id"), table_name="export_snapshots")
    op.drop_index(op.f("ix_ingest_jobs_requested_by_user_id"), table_name="ingest_jobs")
    op.drop_index("ix_nodes_workspace_id_rank", table_name="nodes")
    op.drop_index("ix_projects_updated_at", table_name="projects")
    op.drop_index("ix_projects_user_id_updated_at", table_name="projects")

    op.create_index(
        op.f("ix_workspace_chat_messages_workspace_id"),
        "workspace_chat_messages",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_nodes_workspace_id"),
        "nodes",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspaces_project_id"),
        "workspaces",
        ["project_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_projects_user_id"),
        "projects",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_users_email"),
        "users",
        ["email"],
        unique=False,
    )
