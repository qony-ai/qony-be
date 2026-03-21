from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workspace_chat_message import WorkspaceChatMessage


class WorkspaceChatMessageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_workspace(self, workspace_id: UUID) -> list[WorkspaceChatMessage]:
        statement = (
            select(WorkspaceChatMessage)
            .where(WorkspaceChatMessage.workspace_id == workspace_id)
            .order_by(WorkspaceChatMessage.created_at.asc(), WorkspaceChatMessage.id.asc())
        )
        return list(self.session.scalars(statement))

    def create(
        self,
        *,
        project_id: UUID,
        workspace_id: UUID,
        role: str,
        content: str,
        graph_version: int | None,
        applied_commands: list[str] | None = None,
        metadata: dict | None = None,
        user_id: UUID | None = None,
        ai_request_log_id: UUID | None = None,
    ) -> WorkspaceChatMessage:
        message = WorkspaceChatMessage(
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user_id,
            ai_request_log_id=ai_request_log_id,
            role=role,
            content=content,
            graph_version=graph_version,
            applied_commands_json=applied_commands or [],
            metadata_json=metadata or {},
        )
        self.session.add(message)
        self.session.flush()
        return message
