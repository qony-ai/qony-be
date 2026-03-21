from __future__ import annotations

from io import BytesIO

from fastapi import UploadFile

from app.core.exceptions import DomainValidationError

MAX_INGEST_FILE_BYTES = 10 * 1024 * 1024


async def extract_text_from_upload(upload: UploadFile) -> str:
    content = await upload.read()
    if not content:
        raise DomainValidationError("Uploaded file is empty.")
    if len(content) > MAX_INGEST_FILE_BYTES:
        raise DomainValidationError(
            "Uploaded file exceeds the 10 MB ingest limit.",
            details={"max_bytes": MAX_INGEST_FILE_BYTES},
        )

    filename = (upload.filename or "").lower()
    content_type = (upload.content_type or "").lower()

    if filename.endswith(".pdf") or content_type == "application/pdf":
        return extract_text_from_pdf_bytes(content)
    if filename.endswith(".txt") or content_type.startswith("text/plain"):
        return content.decode("utf-8", errors="ignore").strip()

    raise DomainValidationError(
        "Unsupported ingest file type. Only PDF and TXT are currently supported.",
        details={"filename": upload.filename, "content_type": upload.content_type},
    )


def extract_text_from_pdf_bytes(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as exc:
        raise DomainValidationError(
            "PDF ingest requires the optional 'pypdf' dependency. Reinstall backend dependencies first."
        ) from exc

    reader = PdfReader(BytesIO(content))
    page_text = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(part.strip() for part in page_text if part.strip()).strip()
    if not text:
        raise DomainValidationError("The uploaded PDF does not contain extractable text.")
    return text
