import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, TypeAdapter

from app.core.config import Settings
from app.core.exceptions import ExternalServiceError
from app.integrations.ai.base import AIProvider
from app.schemas.export import ExportChain
from app.schemas.workspace import MutationCommand, WorkspaceGraph


class _CommandEnvelope(BaseModel):
    commands: list[MutationCommand] = Field(default_factory=list)
    rationale: str | None = None


class RemoteAIProvider(AIProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider_name = "remote"
        self.model_name = settings.ai_remote_model
        self._command_adapter = TypeAdapter(_CommandEnvelope)

    def generate_ingest_commands(
        self,
        *,
        project_id: UUID,
        raw_text: str,
    ) -> tuple[list[MutationCommand], str | None]:
        envelope = self._chat_for_commands(
            system_prompt=(
                "You structure raw problem statements into a strict 6-rank DAG. "
                "Return JSON only with a commands array using add_node and add_edge. "
                "Allowed transitions are exactly 1->2->3->4->5->6. "
                "Do not create cycles, do not create more than 24 commands, and mark AI-generated nodes with source='ai'."
            ),
            user_prompt=f"Project ID: {project_id}\nRaw text:\n{raw_text}",
        )
        return envelope.commands, envelope.rationale

    def generate_workspace_patch(
        self,
        *,
        project_id: UUID,
        graph: WorkspaceGraph,
        instruction: str,
    ) -> tuple[list[MutationCommand], str | None]:
        envelope = self._chat_for_commands(
            system_prompt=(
                "You mutate a strict ranked DAG. Return JSON only with a commands array. "
                "Use only add_node, update_node, delete_node, add_edge, delete_edge, move_node. "
                "Never use apply_ai_patch in generated output. All edges must follow exactly one-rank increments."
            ),
            user_prompt=(
                f"Project ID: {project_id}\nInstruction: {instruction}\n"
                f"Current graph JSON:\n{graph.model_dump_json(indent=2)}"
            ),
        )
        return envelope.commands, envelope.rationale

    def generate_export_narrative(
        self,
        *,
        project_id: UUID,
        chains: Sequence[ExportChain],
    ) -> str | None:
        payload = self._chat(
            system_prompt="Summarize the export preview into a concise executive narrative. Return plain text only.",
            user_prompt=(
                f"Project ID: {project_id}\n"
                f"Export chains JSON:\n{json.dumps([chain.model_dump(mode='json') for chain in chains], indent=2)}"
            ),
        )
        return payload.strip() or None

    def _chat_for_commands(self, *, system_prompt: str, user_prompt: str) -> _CommandEnvelope:
        content = self._chat(system_prompt=system_prompt, user_prompt=user_prompt)
        try:
            return self._command_adapter.validate_json(_extract_json(content))
        except Exception as exc:  # noqa: BLE001
            raise ExternalServiceError(
                "Remote AI provider returned malformed JSON for command generation.",
                details={"response_excerpt": content[:500]},
            ) from exc

    def _chat(self, *, system_prompt: str, user_prompt: str) -> str:
        if not self.settings.ai_remote_api_key:
            raise ExternalServiceError("AI_REMOTE_API_KEY is required for the remote AI provider.")

        url = self.settings.ai_remote_base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.settings.ai_remote_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.settings.ai_remote_api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=self.settings.ai_request_timeout_seconds) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Remote AI provider request failed.") from exc

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise ExternalServiceError("Remote AI provider returned no choices.")
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str):
            raise ExternalServiceError("Remote AI provider returned an unsupported content payload.")
        return content


def _extract_json(content: str) -> str:
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response.")
    return content[start : end + 1]

