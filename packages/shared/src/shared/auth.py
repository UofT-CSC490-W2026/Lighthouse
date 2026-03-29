from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request


async def verify_internal_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """Validate the internal service bearer token.

    Reads the expected token from ``request.app.state.settings.internal_service_token``.
    Validation is skipped when the token is empty (e.g. local development).
    """
    token: str = request.app.state.settings.internal_service_token
    if not token:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header",
        )
    if not secrets.compare_digest(token, authorization.removeprefix("Bearer ")):
        raise HTTPException(status_code=401, detail="Invalid token")
