from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import Actor
from app.domain.graph import ensure_valid_graph
from app.repositories.projects import ProjectRepository
from app.repositories.workspace_chat_messages import WorkspaceChatMessageRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository
from app.schemas.workspace import (
    WorkspaceChatRequest,
    WorkspaceChatResponse,
    WorkspaceMutationRequest,
    WorkspaceMutationResult,
    WorkspacePayload,
)
from app.services.ai_service import AIService
from app.services.graph_mapper import workspace_chat_message_to_read, workspace_to_graph, workspace_to_payload


class WorkspaceService:
    def __init__(self, *, session: Session, settings: Settings, actor: Actor) -> None:
        self.session = session
        self.settings = settings
        self.actor = actor
        self.user_repository = UserRepository(session)
        self.project_repository = ProjectRepository(session)
        self.workspace_repository = WorkspaceRepository(session)
        self.workspace_chat_repository = WorkspaceChatMessageRepository(session)
        self.ai_service = AIService(session=session, settings=settings, actor=actor)

    def get_workspace(self, project_id) -> WorkspacePayload:
        project = self._resolve_project(project_id)
        if project is None:
            raise NotFoundError("Project not found.")
        workspace = self.workspace_repository.get_by_project_id(project.id)
        if workspace is None:
            raise NotFoundError("Workspace not found.")
        chat_messages = self.workspace_chat_repository.list_for_workspace(workspace.id)
        return workspace_to_payload(workspace, chat_messages=chat_messages)

    def mutate_workspace(self, payload: WorkspaceMutationRequest) -> WorkspaceMutationResult:
        user = self.user_repository.get_or_create(email=self.actor.email, name=self.actor.name)
        project = self._resolve_project(payload.project_id)
        if project is None:
            raise NotFoundError("Project not found.")
        workspace = self.workspace_repository.get_by_project_id(project.id)
        if workspace is None:
            raise NotFoundError("Workspace not found.")
        if payload.expected_version is not None and payload.expected_version != workspace.version:
            raise ConflictError(
                "Workspace version conflict.",
                details={"expected_version": payload.expected_version, "actual_version": workspace.version},
            )

        current_graph = workspace_to_graph(workspace)
        ai_request_id = None

        def resolve_ai_patch(graph_state, command: ApplyAIPatchCommand):
            nonlocal ai_request_id
            suggestion = self.ai_service.generate_mutation_patch(
                project_id=project.id,
                workspace_id=workspace.id,
                user_id=user.id,
                graph=graph_state,
                command=command,
            )
            ai_request_id = suggestion.provider_result.request_log_id
            return suggestion.commands

        mutated_graph, applied_commands, ai_commands_applied = apply_mutation_commands(
            current_graph,
            payload.commands,
            ai_command_resolver=resolve_ai_patch,
        )
        ensure_valid_graph(mutated_graph)
        refreshed_workspace = self.workspace_repository.sync_graph(workspace, mutated_graph)
        self.session.commit()
        graph = workspace_to_graph(refreshed_workspace)
        return WorkspaceMutationResult(
            project_id=project.id,
            workspace_id=refreshed_workspace.id,
            graph=graph,
            applied_commands=applied_commands,
            ai_commands_applied=ai_commands_applied,
            ai_request_id=ai_request_id,
        )

    def chat_workspace(self, payload: WorkspaceChatRequest) -> WorkspaceChatResponse:
        user = self.user_repository.get_or_create(email=self.actor.email, name=self.actor.name)
        project = self._resolve_project(payload.project_id)
        if project is None:
            raise NotFoundError("Project not found.")
        workspace = self.workspace_repository.get_by_project_id(project.id)
        if workspace is None:
            raise NotFoundError("Workspace not found.")
        if payload.expected_version is not None and payload.expected_version != workspace.version:
            raise ConflictError(
                "Workspace version conflict.",
                details={"expected_version": payload.expected_version, "actual_version": workspace.version},
            )

        current_graph = workspace_to_graph(workspace)
        suggestion = self.ai_service.rewrite_workspace_graph(
            project_id=project.id,
            workspace_id=workspace.id,
            user_id=user.id,
            graph=current_graph,
            instruction=payload.message,
        )
        if suggestion.action == "rewrite_graph" and suggestion.graph is not None:
            ensure_valid_graph(suggestion.graph)
            applied_commands = self.ai_service.build_graph_change_actions(
                current_graph=current_graph,
                rewritten_graph=suggestion.graph,
            )
            if applied_commands:
                refreshed_workspace = self.workspace_repository.sync_graph(workspace, suggestion.graph)
                graph = workspace_to_graph(refreshed_workspace)
            else:
                refreshed_workspace = workspace
                graph = current_graph
        elif suggestion.action == "explain":
            applied_commands = []
            refreshed_workspace = workspace
            graph = current_graph
        else:
            raise ConflictError("Workspace chat response did not produce a usable action.")

        self.workspace_chat_repository.create(
            project_id=project.id,
            workspace_id=refreshed_workspace.id,
            user_id=user.id,
            role="user",
            content=payload.message,
            graph_version=current_graph.metadata.version,
            metadata={
                "origin": "workspace_chat",
                "action": suggestion.action,
            },
        )
        assistant_message = self.workspace_chat_repository.create(
            project_id=project.id,
            workspace_id=refreshed_workspace.id,
            ai_request_log_id=suggestion.provider_result.request_log_id,
            role="assistant",
            content=suggestion.summary or "No assistant response was produced.",
            graph_version=graph.metadata.version,
            applied_commands=applied_commands,
            metadata={
                "provider": suggestion.provider_result.provider,
                "fallback_used": suggestion.provider_result.fallback_used,
                "action": suggestion.action,
                "request_payload": suggestion.request_payload,
                "response_payload": suggestion.response_payload,
            },
        )
        self.session.commit()

        chat_messages = self.workspace_chat_repository.list_for_workspace(refreshed_workspace.id)
        return WorkspaceChatResponse(
            project_id=project.id,
            workspace_id=refreshed_workspace.id,
            graph=graph,
            chat={"messages": [workspace_chat_message_to_read(message) for message in chat_messages]},
            assistant_message=workspace_chat_message_to_read(assistant_message),
            applied_commands=applied_commands,
            ai_commands_applied=len(applied_commands),
            ai_request_id=suggestion.provider_result.request_log_id,
        )

    def _resolve_project(self, project_id):
        if self.actor.source == "default":
            return self.project_repository.get_by_id(project_id)
        user = self.user_repository.get_or_create(email=self.actor.email, name=self.actor.name)
        return self.project_repository.get_for_user(project_id, user.id)
