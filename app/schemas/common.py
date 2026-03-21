from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ResponseMeta(BaseModel):
    request_id: str | None = None
    timestamp: datetime | None = None


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: ResponseMeta | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class DeleteResult(BaseModel):
    deleted: bool = True


ApiEnvelope = Envelope
ErrorPayload = ErrorBody
ErrorEnvelope = ErrorResponse

