from collections.abc import Sequence
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings
from app.core.exceptions import ExternalServiceError
from app.integrations.ai.remote import RemoteAIProvider, _CommandEnvelope, _extract_json
from app.schemas.export import ExportChain
from app.schemas.workspace import MutationCommand, WorkspaceGraph


class OllamaAIProvider(RemoteAIProvider):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.provider_name = "ollama"
        self.model_name = settings.ollama_model

    def generate_ingest_commands(
        self,
        *,
        project_id: UUID,
        raw_text: str,
    ) -> tuple[list[MutationCommand], str | None]:
        envelope = self._chat_for_commands(
            system_prompt=(
                "Return JSON only with add_node and add_edge commands for a strict 6-rank DAG. "
                "Allowed transitions are exactly 1->2->3->4->5->6."
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
                "Return JSON only with graph mutation commands. "
                "Use only add_node, update_node, delete_node, add_edge, delete_edge, move_node. "
                "Do not generate apply_ai_patch."
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
        return self._chat(
            system_prompt="Summarize the export chains into a concise executive narrative. Return plain text only.",
            user_prompt="\n".join(step.title for chain in chains for step in chain.steps[:1]),
        )

    def _chat(self, *, system_prompt: str, user_prompt: str) -> str:
        url = self.settings.ollama_base_url.rstrip("/") + "/api/chat"
        payload: dict[str, Any] = {
            "model": self.settings.ollama_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": "json",
            "options": {"temperature": 0.1},
        }

        try:
            with httpx.Client(timeout=self.settings.ai_request_timeout_seconds) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Ollama request failed.") from exc

        data = response.json()
        message = data.get("message", {})
        content = message.get("content") or data.get("response")
        if not isinstance(content, str):
            raise ExternalServiceError("Ollama returned an unsupported response payload.")
        return content

