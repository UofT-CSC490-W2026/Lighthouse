from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from shared.auth import verify_internal_token


def _make_request(token: str, authorization: str | None = None):
    """Build a minimal fake FastAPI Request with app.state.settings."""
    settings = SimpleNamespace(internal_service_token=token)
    state = SimpleNamespace(settings=settings)
    app = SimpleNamespace(state=state)
    request = MagicMock()
    request.app = app
    return request


@pytest.mark.asyncio
async def test_verify_internal_token_skips_when_empty():
    """No token configured → always passes."""
    request = _make_request(token="")
    # Should not raise regardless of Authorization header
    await verify_internal_token(request, authorization=None)
    await verify_internal_token(request, authorization="Bearer anything")


@pytest.mark.asyncio
async def test_verify_internal_token_missing_header_raises_401():
    request = _make_request(token="secret")
    with pytest.raises(HTTPException) as exc_info:
        await verify_internal_token(request, authorization=None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_internal_token_malformed_header_raises_401():
    request = _make_request(token="secret")
    with pytest.raises(HTTPException) as exc_info:
        await verify_internal_token(request, authorization="Token secret")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_internal_token_wrong_token_raises_401():
    request = _make_request(token="correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await verify_internal_token(request, authorization="Bearer wrong-secret")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_internal_token_correct_token_passes():
    request = _make_request(token="correct-secret")
    await verify_internal_token(request, authorization="Bearer correct-secret")
