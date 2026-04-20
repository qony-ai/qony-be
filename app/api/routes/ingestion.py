from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile, WebSocket, WebSocketDisconnect, status

from app.api.deps import get_actor, get_prd_ingestion_service, get_settings
from app.core.config import Settings
from app.core.security import Actor
from app.schemas.common import ApiEnvelope
from app.schemas.ingest import IngestJobRead
from app.services.ingest_service import PRDIngestionService, progress_broker

router = APIRouter(tags=["ingestion"])


@router.post("/projects/{project_id}/ingest", response_model=ApiEnvelope[IngestJobRead], status_code=status.HTTP_202_ACCEPTED)
async def start_ingestion(
    project_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    service: PRDIngestionService = Depends(get_prd_ingestion_service),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(get_actor),
) -> ApiEnvelope[IngestJobRead]:
    suffix = Path(file.filename or "upload.txt").suffix or ".txt"
    tmp_dir = Path(tempfile.mkdtemp(prefix="qony-upload-"))
    file_path = tmp_dir / f"source{suffix}"
    file_path.write_bytes(await file.read())

    job = service.create_job(
        project_id=project_id,
        source_filename=file.filename,
        source_content_type=file.content_type,
        metadata={"upload_path": str(file_path)},
    )

    session_factory = request.app.state.session_factory

    async def run_ingestion_job() -> None:
        session = session_factory()
        try:
            runner = PRDIngestionService(session=session, settings=settings, actor=actor)
            await runner.process_document(file_path=str(file_path), project_id=project_id, job_id=job.id)
        finally:
            session.close()

    asyncio.create_task(run_ingestion_job())
    return ApiEnvelope(data=job)


@router.websocket("/ws/ingest/{job_id}")
async def ingest_progress_socket(websocket: WebSocket, job_id: UUID) -> None:
    await websocket.accept()
    queue = await progress_broker.subscribe(str(job_id))
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event.get("event") in {"complete", "failed"}:
                break
    except WebSocketDisconnect:
        pass
    finally:
        progress_broker.unsubscribe(str(job_id), queue)
