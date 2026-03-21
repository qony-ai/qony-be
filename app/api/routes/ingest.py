from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request, UploadFile, status
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api.deps import get_ingest_service
from app.core.exceptions import DomainValidationError
from app.schemas.common import ApiEnvelope
from app.schemas.ingest import IngestRequest, IngestResponseData
from app.services.file_ingest import extract_text_from_upload
from app.services.ingest_service import IngestService

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("", response_model=ApiEnvelope[IngestResponseData], status_code=status.HTTP_201_CREATED)
async def ingest(
    request: Request,
    service: IngestService = Depends(get_ingest_service),
) -> ApiEnvelope[IngestResponseData]:
    try:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            _ensure_multipart_support()
            form = await request.form()
            raw_text = _as_optional_str(form.get("raw_text"))
            upload = form.get("file")
            source_filename = _as_optional_str(form.get("source_filename"))
            source_content_type = _as_optional_str(form.get("source_content_type"))

            if isinstance(upload, (UploadFile, StarletteUploadFile)):
                if not raw_text:
                    raw_text = await extract_text_from_upload(upload)
                source_filename = source_filename or upload.filename
                source_content_type = source_content_type or upload.content_type
            elif not raw_text:
                raise DomainValidationError("Provide either raw_text or a supported upload file.")

            metadata_value = form.get("metadata")
            metadata = _parse_metadata(metadata_value)
            if isinstance(upload, (UploadFile, StarletteUploadFile)):
                metadata.setdefault("upload_filename", upload.filename)
                metadata.setdefault("upload_content_type", upload.content_type)

            payload = IngestRequest(
                project_id=str(form.get("project_id", "")).strip(),
                raw_text=raw_text,
                source_filename=source_filename,
                source_content_type=source_content_type,
                replace_existing=_parse_bool(form.get("replace_existing")),
                metadata=metadata,
            )
        else:
            payload = IngestRequest.model_validate(await request.json())
    except ValidationError as exc:
        raise DomainValidationError(
            "The ingest request payload failed validation.",
            details=exc.errors(),
        ) from exc
    return ApiEnvelope(data=service.ingest(payload))


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_metadata(value) -> dict:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise DomainValidationError("metadata must be valid JSON when sent as form-data.") from exc
    if not isinstance(parsed, dict):
        raise DomainValidationError("metadata must be a JSON object.")
    return parsed


def _as_optional_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _ensure_multipart_support() -> None:
    try:
        import multipart  # noqa: F401
    except ModuleNotFoundError as exc:
        raise DomainValidationError(
            "File upload ingest requires the 'python-multipart' dependency. Reinstall backend dependencies first."
        ) from exc
