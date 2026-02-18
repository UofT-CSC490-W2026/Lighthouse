"""Centralized application error types for MCP HTTP error mapping."""

from __future__ import annotations


class MCPServiceError(RuntimeError):
    """Base class for structured MCP API errors."""

    status_code: int = 500
    code: str = "MCP_INTERNAL_ERROR"

    def __init__(self, message: str, *, details: object | None = None) -> None:
        """Initialize a structured API error with optional machine-readable details."""
        super().__init__(message)
        self.message = message
        self.details = details


class RequestValidationAppError(MCPServiceError):
    """Raised for malformed request payloads or invalid parameter values."""

    status_code = 400
    code = "REQUEST_VALIDATION_ERROR"


class ResourceNotFoundError(MCPServiceError):
    """Raised when a requested API resource does not exist."""

    status_code = 404
    code = "RESOURCE_NOT_FOUND"


class BackendUnavailableError(MCPServiceError):
    """Raised when required backend dependencies are unavailable."""

    status_code = 503
    code = "BACKEND_UNAVAILABLE"


class AuthenticationRequiredError(MCPServiceError):
    """Raised when a request is missing required authentication credentials."""

    status_code = 401
    code = "AUTHENTICATION_REQUIRED"


class WorkflowExecutionError(MCPServiceError):
    """Raised when workflow orchestration operations fail."""

    status_code = 502
    code = "WORKFLOW_EXECUTION_ERROR"
