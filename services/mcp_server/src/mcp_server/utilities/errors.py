from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ErrorEnvelope(BaseModel):
    """Public-facing, machine-readable error payload."""

    message: str
    error_code: str
    error_id: str
    recoverable: bool
    context: dict[str, Any] = Field(default_factory=dict)


class RequestError(Exception):
    """Represent a client-facing request error with an explicit status code."""

    def __init__(self, detail: str, status_code: int = 400) -> None:
        """Create a request error with a serialized message and HTTP status."""
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class AppError(RequestError):
    """Structured request error with separate public and internal diagnostics."""

    def __init__(
        self,
        *,
        message: str,
        status_code: int,
        error_code: str,
        recoverable: bool,
        context: dict[str, Any] | None = None,
        internal_message: str | None = None,
        upstream_detail: Any | None = None,
        cause_metadata: dict[str, Any] | None = None,
        error_id: str | None = None,
    ) -> None:
        super().__init__(detail=message, status_code=status_code)
        self.message = message
        self.error_code = error_code
        self.recoverable = recoverable
        self.context = context or {}
        self.internal_message = internal_message
        self.upstream_detail = upstream_detail
        self.cause_metadata = cause_metadata or {}
        self.error_id = error_id or generate_error_id()

    def to_envelope(self) -> ErrorEnvelope:
        """Serialize the safe public error payload."""
        return ErrorEnvelope(
            message=self.message,
            error_code=self.error_code,
            error_id=self.error_id,
            recoverable=self.recoverable,
            context=self.context,
        )


def generate_error_id() -> str:
    """Generate a compact error correlation identifier."""
    return f"err_{uuid4().hex[:12]}"


def default_error_code_for_status(status_code: int) -> str:
    """Map HTTP status code classes to default application error codes."""
    if status_code == 401:
        return "AUTH_REQUIRED"
    if status_code == 403:
        return "FORBIDDEN"
    if status_code == 404:
        return "REPOSITORY_NOT_FOUND_OR_INACCESSIBLE"
    if status_code == 409:
        return "CONFLICT"
    if status_code in (400, 422):
        return "INVALID_ARGUMENT"
    if status_code in (502, 503, 504):
        return "UPSTREAM_UNAVAILABLE"
    return "INTERNAL_ERROR" if status_code >= 500 else "INVALID_ARGUMENT"


def to_public_error(exc: Exception) -> tuple[int, ErrorEnvelope]:
    """Convert an exception to status code + public envelope."""
    if isinstance(exc, AppError):
        return exc.status_code, exc.to_envelope()

    if isinstance(exc, RequestError):
        status_code = exc.status_code
        envelope = ErrorEnvelope(
            message=exc.detail,
            error_code=default_error_code_for_status(status_code),
            error_id=generate_error_id(),
            recoverable=status_code < 500,
            context={},
        )
        return status_code, envelope

    envelope = ErrorEnvelope(
        message="An internal server error occurred.",
        error_code="INTERNAL_ERROR",
        error_id=generate_error_id(),
        recoverable=False,
        context={},
    )
    return 500, envelope


def log_error(logger: logging.Logger, exc: Exception, envelope: ErrorEnvelope) -> None:
    """Log internal diagnostics correlated to a public error envelope."""
    if isinstance(exc, AppError):
        logger.error(
            "error_id=%s code=%s message=%s internal_message=%s upstream_detail=%r cause_metadata=%r context=%r",
            envelope.error_id,
            exc.error_code,
            exc.message,
            exc.internal_message,
            exc.upstream_detail,
            exc.cause_metadata,
            exc.context,
        )
        return

    logger.exception(
        "error_id=%s code=%s message=%s",
        envelope.error_id,
        envelope.error_code,
        envelope.message,
    )
