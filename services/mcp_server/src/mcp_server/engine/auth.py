from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ..utilities import AuthenticatedUser, get_logger, httproute

if TYPE_CHECKING:
    from .engine import Engine


class AuthEngine:
    """Handle OAuth bootstrap and bearer-token lifecycle routes."""

    def __init__(self, engine: Engine) -> None:
        """Bind the auth engine to the shared engine."""
        self.engine = engine
        self.log = get_logger(__name__)

    @httproute(
        "GET",
        "/v1/auth/github",
        name="github_authorize",
        description="Start the GitHub OAuth flow.",
        auth_required=False,
    )
    def github_authorize(self) -> RedirectResponse:
        """Start GitHub OAuth and persist a short-lived CSRF state cookie."""
        state = self.engine.app.authenticator.generate_state()
        url = self.engine.app.authenticator.build_authorize_url(state)
        response = RedirectResponse(url=url, status_code=307)
        response.set_cookie(
            key="oauth_state",
            value=state,
            httponly=True,
            secure=not self.engine.app.settings.debug,
            samesite="lax",
            max_age=600,
            path="/",
        )
        return response

    @httproute(
        "GET",
        "/v1/auth/github/callback",
        name="github_callback",
        description="Finish the GitHub OAuth flow and issue a Lighthouse API token.",
        auth_required=False,
    )
    async def github_callback(
        self,
        request: Request,
        code: Annotated[str, Query(...)],
        state: Annotated[str, Query()] = "",
    ) -> RedirectResponse:
        """Finish GitHub OAuth, mint a Lighthouse token, and redirect back to the web app."""
        expected_state = request.cookies.get("oauth_state")
        if not expected_state or state != expected_state:
            return RedirectResponse(
                url=self.engine.app.authenticator.build_oauth_error_redirect(
                    "invalid_state"
                ),
                status_code=302,
            )

        try:
            access_token = await self.engine.app.authenticator.exchange_code_for_token(
                code
            )
            github_user = await self.engine.app.authenticator.fetch_github_user(
                access_token
            )
            _, api_token = (
                await self.engine.app.authenticator.upsert_github_user_and_issue_token(
                    github_user,
                    access_token,
                )
            )
        except Exception:
            self.log.exception("OAuth callback failed")
            return RedirectResponse(
                url=self.engine.app.authenticator.build_oauth_error_redirect(
                    "oauth_failed"
                ),
                status_code=302,
            )

        response = RedirectResponse(
            url=self.engine.app.authenticator.build_oauth_success_redirect(api_token),
            status_code=302,
        )
        response.delete_cookie(key="oauth_state", path="/")
        return response

    @httproute(
        "POST",
        "/v1/auth/logout",
        name="logout",
        description="Invalidate the current Lighthouse API token.",
    )
    async def logout(self, auth: AuthenticatedUser) -> Response:
        """Revoke the caller's current Lighthouse bearer token."""
        if auth.authenticated_via == "mcp":
            await self.engine.app.authenticator.revoke_mcp_token(auth.id)
        else:
            await self.engine.app.authenticator.revoke_token(auth.id)
        return Response(status_code=204)

    @httproute(
        "GET",
        "/v1/auth/mcp-token",
        name="get_mcp_token",
        description="Return the current long-lived MCP token for the authenticated user.",
    )
    async def get_mcp_token(self, auth: AuthenticatedUser) -> "MCPTokenResponse":
        """Return the user's current long-lived MCP token and issuance metadata."""
        token = await self.engine.app.authenticator.get_mcp_token(auth.id)
        return MCPTokenResponse(
            token=token.token,
            issued_at=token.issued_at,
            has_token=token.token is not None,
        )

    @httproute(
        "POST",
        "/v1/auth/mcp-token",
        name="rotate_mcp_token",
        description="Generate or rotate the user's long-lived MCP token.",
    )
    async def rotate_mcp_token(self, auth: AuthenticatedUser) -> "MCPTokenResponse":
        """Generate a new long-lived MCP token for the user."""
        token = await self.engine.app.authenticator.rotate_mcp_token(auth.id)
        return MCPTokenResponse(
            token=token.token,
            issued_at=token.issued_at,
            has_token=token.token is not None,
        )

    @httproute(
        "DELETE",
        "/v1/auth/mcp-token",
        name="revoke_mcp_token",
        description="Revoke the user's long-lived MCP token.",
    )
    async def revoke_mcp_token(self, auth: AuthenticatedUser) -> Response:
        """Remove the user's long-lived MCP token without affecting the web session."""
        await self.engine.app.authenticator.revoke_mcp_token(auth.id)
        return Response(status_code=204)


class MCPTokenResponse(BaseModel):
    """Serialize the user's long-lived MCP token state."""

    token: str | None
    issued_at: datetime | None
    has_token: bool
