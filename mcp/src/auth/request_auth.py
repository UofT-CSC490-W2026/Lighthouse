"""Parse and validate request-scoped auth credentials for MCP calls."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ..errors import AuthenticationRequiredError

_BEARER_PREFIX = "bearer "
_AUTHORIZATION_HEADER = "authorization"
_GITHUB_TOKEN_HEADER = "x-github-token"


@dataclass(frozen=True, slots=True)
class RequestAuthContext:
    """Authentication data extracted from a single incoming HTTP request."""

    github_token: str | None
    source: str | None


def extract_request_auth(request: Request) -> RequestAuthContext:
    """Extract GitHub token credentials from supported request headers.

    Header precedence:
    1) `Authorization: Bearer <token>`
    2) `X-GitHub-Token: <token>`
    """
    authorization = (request.headers.get(_AUTHORIZATION_HEADER) or "").strip()
    if authorization and authorization.lower().startswith(_BEARER_PREFIX):
        token = authorization[len(_BEARER_PREFIX) :].strip()
        if token:
            return RequestAuthContext(github_token=token, source="authorization_bearer")

    github_token = (request.headers.get(_GITHUB_TOKEN_HEADER) or "").strip()
    if github_token:
        return RequestAuthContext(github_token=github_token, source="x_github_token")

    return RequestAuthContext(github_token=None, source=None)


def require_github_token(request: Request) -> str:
    """Require a GitHub token in request headers or raise a structured auth error."""
    auth = extract_request_auth(request)
    if auth.github_token:
        return auth.github_token

    raise AuthenticationRequiredError(
        "GitHub token required for indexing control operations. "
        "Provide 'Authorization: Bearer <token>' (or 'X-GitHub-Token')."
    )
