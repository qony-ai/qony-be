from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.ai_request_log import AIRequestLog


class AIRequestLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        project_id: UUID | None,
        workspace_id: UUID | None,
        user_id: UUID | None,
        operation: str,
        provider: str,
        model: str | None,
        status: str,
        fallback_used: bool,
        prompt_digest: str,
        latency_ms: int | None,
        request_excerpt: str | None,
        response_excerpt: str | None,
        error_message: str | None,
        metadata: dict,
    ) -> AIRequestLog:
        log = AIRequestLog(
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user_id,
            operation=operation,
            provider=provider,
            model=model,
            status=status,
            fallback_used=fallback_used,
            prompt_digest=prompt_digest,
            latency_ms=latency_ms,
            request_excerpt=request_excerpt,
            response_excerpt=response_excerpt,
            error_message=error_message,
            metadata_json=metadata,
        )
        self.session.add(log)
        self.session.flush()
        return log
