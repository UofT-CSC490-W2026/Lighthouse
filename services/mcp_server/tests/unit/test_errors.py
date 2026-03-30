from __future__ import annotations

from mcp_server.utilities.errors import (
    AppError,
    RequestError,
    default_error_code_for_status,
    to_public_error,
)


def test_app_error_public_envelope_excludes_internal_details():
    exc = AppError(
        message="Public message",
        status_code=502,
        error_code="UPSTREAM_ERROR",
        recoverable=True,
        context={"service": "search"},
        internal_message="private debug message",
        upstream_detail={"secret": "value"},
        cause_metadata={"trace": "hidden"},
    )

    status, envelope = to_public_error(exc)
    payload = envelope.model_dump(mode="json")

    assert status == 502
    assert payload["message"] == "Public message"
    assert payload["error_code"] == "UPSTREAM_ERROR"
    assert payload["recoverable"] is True
    assert payload["context"] == {"service": "search"}
    assert "error_id" in payload
    assert "internal_message" not in payload
    assert "upstream_detail" not in payload
    assert "cause_metadata" not in payload


def test_plain_request_error_is_wrapped_with_default_code():
    status, envelope = to_public_error(RequestError("bad input", status_code=422))
    payload = envelope.model_dump(mode="json")

    assert status == 422
    assert payload["message"] == "bad input"
    assert payload["error_code"] == "INVALID_ARGUMENT"
    assert payload["recoverable"] is True


def test_default_error_code_mapping():
    assert default_error_code_for_status(401) == "AUTH_REQUIRED"
    assert default_error_code_for_status(409) == "CONFLICT"
    assert default_error_code_for_status(500) == "INTERNAL_ERROR"


def test_default_error_code_mapping_upstream_unavailable():
    assert default_error_code_for_status(502) == "UPSTREAM_UNAVAILABLE"
    assert default_error_code_for_status(503) == "UPSTREAM_UNAVAILABLE"
    assert default_error_code_for_status(504) == "UPSTREAM_UNAVAILABLE"


def test_default_error_code_mapping_forbidden():
    assert default_error_code_for_status(403) == "FORBIDDEN"


def test_to_public_error_with_generic_exception():
    """A non-RequestError exception should map to 500 INTERNAL_ERROR."""
    exc = RuntimeError("something went very wrong")
    status_code, envelope = to_public_error(exc)
    payload = envelope.model_dump(mode="json")

    assert status_code == 500
    assert payload["message"] == "An internal server error occurred."
    assert payload["error_code"] == "INTERNAL_ERROR"
    assert payload["recoverable"] is False
    assert "error_id" in payload


def test_default_error_code_for_404():
    """Line 79: 404 maps to REPOSITORY_NOT_FOUND_OR_INACCESSIBLE."""
    assert default_error_code_for_status(404) == "REPOSITORY_NOT_FOUND_OR_INACCESSIBLE"
