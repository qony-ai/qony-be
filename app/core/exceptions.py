from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found", *, details: Any | None = None) -> None:
        super().__init__(code="not_found", message=message, status_code=404, details=details)


class ConflictError(AppError):
    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(code="conflict", message=message, status_code=409, details=details)


class AuthenticationError(AppError):
    def __init__(self, message: str = "Authentication required", *, details: Any | None = None) -> None:
        super().__init__(
            code="authentication_required",
            message=message,
            status_code=401,
            details=details,
        )


class DomainValidationError(AppError):
    def __init__(self, message: str = "Domain validation failed", *, details: Any | None = None) -> None:
        super().__init__(
            code="domain_validation_error",
            message=message,
            status_code=422,
            details=details,
        )


class AuthorizationError(AppError):
    def __init__(self, message: str = "Forbidden", *, details: Any | None = None) -> None:
        super().__init__(
            code="forbidden",
            message=message,
            status_code=403,
            details=details,
        )


class AIProviderError(AppError):
    def __init__(self, message: str = "AI provider unavailable", *, details: Any | None = None) -> None:
        super().__init__(
            code="ai_provider_unavailable",
            message=message,
            status_code=503,
            details=details,
        )


class ExternalServiceError(AIProviderError):
    pass


class ServiceUnavailableError(AppError):
    def __init__(self, message: str = "Service unavailable", *, details: Any | None = None) -> None:
        super().__init__(
            code="service_unavailable",
            message=message,
            status_code=503,
            details=details,
        )
