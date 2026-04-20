from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.ingest_job import IngestJob


class IngestJobRepository:
    model_class = IngestJob

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_pending(
        self,
        *,
        project_id: UUID,
        workspace_id: UUID,
        requested_by_user_id: UUID,
        raw_text: str,
        source_filename: str | None,
        source_content_type: str | None,
        provider: str,
        metadata: dict,
    ) -> IngestJob:
        job = IngestJob(
            project_id=project_id,
            workspace_id=workspace_id,
            requested_by_user_id=requested_by_user_id,
            raw_text=raw_text,
            source_filename=source_filename,
            source_content_type=source_content_type,
            provider=provider,
            metadata_json=metadata,
            status="pending",
        )
        self.session.add(job)
        self.session.flush()
        return job

    def mark_completed(
        self,
        job: IngestJob,
        *,
        provider: str,
        model: str | None,
        fallback_used: bool,
        output_graph_json: dict,
    ) -> IngestJob:
        job.status = "completed"
        job.provider = provider
        job.model = model
        job.fallback_used = fallback_used
        job.output_graph_json = output_graph_json
        job.error_message = None
        self.session.flush()
        return job

    def mark_failed(self, job: IngestJob, *, error_message: str) -> IngestJob:
        job.status = "failed"
        job.error_message = error_message
        self.session.flush()
        return job
