from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found", details: Any | None = None) -> None:
        super().__init__(status_code=404, code="not_found", message=message, details=details)


class ConflictError(AppError):
    def __init__(self, message: str, details: Any | None = None) -> None:
        super().__init__(status_code=409, code="conflict", message=message, details=details)


class DomainValidationError(AppError):
    def __init__(self, message: str = "Graph validation failed", details: Any | None = None) -> None:
        super().__init__(
            status_code=422,
            code="domain_validation_error",
            message=message,
            details=details,
        )


class AIProviderError(AppError):
    def __init__(self, message: str = "AI provider unavailable", details: Any | None = None) -> None:
        super().__init__(status_code=503, code="ai_provider_unavailable", message=message, details=details)
