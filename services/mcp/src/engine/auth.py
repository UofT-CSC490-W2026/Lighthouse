from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Query, Request, Response
from fastapi.responses import RedirectResponse

from ..utilities import AuthenticatedUser, get_logger, httproute

if TYPE_CHECKING:
    from .engine import Engine


class AuthService:
    """Handle OAuth bootstrap and bearer-token lifecycle routes."""

    def __init__(self, engine: Engine) -> None:
        """Bind the auth service to the shared engine."""
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
                    github_user
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
        await self.engine.app.authenticator.revoke_token(auth.id)
        return Response(status_code=204)
