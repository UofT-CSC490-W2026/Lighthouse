from __future__ import annotations

import asyncio
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet
from fastmcp import Context
from fastapi import Request

from ..models import User
from .errors import RequestError

if TYPE_CHECKING:
    from ..main import App


_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_URL = "https://api.github.com/user"
OAUTH_SCOPES = "read:user read:org repo"


class AuthorizationError(RequestError):
    """Represent an authentication or authorization failure."""

    def __init__(self, detail: str = "Not authenticated", status_code: int = 401) -> None:
        """Create an auth error with a default unauthorized status."""
        super().__init__(detail=detail, status_code=status_code)


@dataclass(frozen=True, slots=True)
class GitHubUser:
    """Hold GitHub profile fields returned from the OAuth user lookup."""

    id: int
    login: str
    name: str | None
    avatar_url: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Hold the authenticated Lighthouse user context injected into handlers."""

    id: str
    github_id: int
    github_login: str
    display_name: str | None
    avatar_url: str | None
    email: str | None
    api_token_issued_at: datetime | None


class Authenticator:
    """Own OAuth bootstrap, token issuance, and bearer-token validation."""

    def __init__(self, app: App) -> None:
        """Bind the authenticator to the application state."""
        self.app = app

    def generate_state(self) -> str:
        """Generate a CSRF state token for GitHub OAuth."""
        return secrets.token_urlsafe(32)

    def generate_api_token(self) -> str:
        """Generate a new Lighthouse bearer token."""
        return secrets.token_urlsafe(32)

    def build_authorize_url(self, state: str) -> str:
        """Build the GitHub OAuth authorization URL for the given state."""
        if not self.app.settings.github_oauth_client_id:
            raise RuntimeError("GITHUB_OAUTH_CLIENT_ID is required")

        params: dict[str, str] = {
            "client_id": self.app.settings.github_oauth_client_id,
            "scope": OAUTH_SCOPES,
            "state": state,
        }
        if self.app.settings.github_oauth_callback_url:
            params["redirect_uri"] = self.app.settings.github_oauth_callback_url
        return f"{_GITHUB_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str) -> str:
        """Exchange a GitHub OAuth code for an access token."""
        if not self.app.settings.github_oauth_client_id:
            raise RuntimeError("GITHUB_OAUTH_CLIENT_ID is required")
        if not self.app.settings.github_oauth_client_secret:
            raise RuntimeError("GITHUB_OAUTH_CLIENT_SECRET is required")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                _GITHUB_TOKEN_URL,
                data={
                    "client_id": self.app.settings.github_oauth_client_id,
                    "client_secret": self.app.settings.github_oauth_client_secret,
                    "code": code,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

        if "error" in data:
            raise RuntimeError(
                f"GitHub OAuth error: {data.get('error_description', data['error'])}"
            )

        token = data.get("access_token")
        if not token:
            raise RuntimeError("No access_token in GitHub response")
        return token

    async def fetch_github_user(self, access_token: str) -> GitHubUser:
        """Fetch the GitHub user profile for an OAuth access token."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                _GITHUB_USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
            data = response.json()

        return GitHubUser(
            id=data["id"],
            login=data["login"],
            name=data.get("name"),
            avatar_url=data.get("avatar_url"),
            email=data.get("email"),
        )

    async def require_http_request(self, request: Request) -> AuthenticatedUser:
        """Authenticate an HTTP request using its bearer token header."""
        return await self.authenticate_bearer_token(
            self.extract_bearer_token(request.headers.get("Authorization"))
        )

    async def require_mcp_context(self, ctx: Context) -> AuthenticatedUser:
        """Authenticate an MCP request using the underlying HTTP headers."""
        request = ctx.request_context.request
        if request is None:
            raise AuthorizationError("Request context is unavailable")
        return await self.authenticate_bearer_token(
            self.extract_bearer_token(request.headers.get("Authorization"))
        )

    async def authenticate_bearer_token(self, token: str) -> AuthenticatedUser:
        """Resolve a plaintext bearer token into authenticated user context."""
        return await asyncio.to_thread(self._authenticate_bearer_token_sync, token)

    async def upsert_github_user_and_issue_token(
        self,
        github_user: GitHubUser,
    ) -> tuple[AuthenticatedUser, str]:
        """Upsert a GitHub user and issue a fresh Lighthouse bearer token."""
        return await asyncio.to_thread(
            self._upsert_github_user_and_issue_token_sync,
            github_user,
        )

    async def revoke_token(self, user_id: str) -> None:
        """Revoke the stored bearer token for a given user."""
        await asyncio.to_thread(self._revoke_token_sync, user_id)

    def extract_bearer_token(self, authorization_header: str | None) -> str:
        """Extract the bearer token value from an Authorization header."""
        if not authorization_header:
            raise AuthorizationError("Missing Authorization header")

        scheme, _, token = authorization_header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AuthorizationError("Authorization header must use Bearer auth")
        return token.strip()

    def encrypt_token(self, plaintext: str) -> str:
        """Encrypt a plaintext bearer token for storage."""
        return self._fernet().encrypt(plaintext.encode()).decode()

    def decrypt_token(self, ciphertext: str) -> str:
        """Decrypt a stored bearer token."""
        return self._fernet().decrypt(ciphertext.encode()).decode()

    def hash_token(self, token: str) -> str:
        """Hash a bearer token for indexed lookup."""
        return hashlib.sha256(token.encode()).hexdigest()

    def build_oauth_success_redirect(self, api_token: str) -> str:
        """Build the post-OAuth success redirect back to the web client."""
        base = self.app.settings.web_client_url.rstrip("/")
        return f"{base}/auth/callback#token={api_token}"

    def build_oauth_error_redirect(self, error: str) -> str:
        """Build the post-OAuth error redirect back to the web client."""
        base = self.app.settings.web_client_url.rstrip("/")
        return f"{base}/login?error={error}"

    def _fernet(self) -> Fernet:
        """Construct the Fernet helper from the configured encryption key."""
        key = self.app.settings.session_encryption_key
        if not key:
            raise RuntimeError("SESSION_ENCRYPTION_KEY is required")
        return Fernet(key.encode() if isinstance(key, str) else key)

    def _authenticate_bearer_token_sync(self, token: str) -> AuthenticatedUser:
        """Validate a bearer token against stored user auth fields."""
        token_hash = self.hash_token(token)
        with self.app.database.connection_context():
            user = User.get_or_none(User.api_token_hash == token_hash)
            if user is None or not user.api_token_encrypted:
                raise AuthorizationError("Invalid or revoked token")

            stored_token = self.decrypt_token(user.api_token_encrypted)
        if not secrets.compare_digest(stored_token, token):
            raise AuthorizationError("Invalid or revoked token")

        return self._to_authenticated_user(user)

    def _upsert_github_user_and_issue_token_sync(
        self,
        github_user: GitHubUser,
    ) -> tuple[AuthenticatedUser, str]:
        """Persist GitHub profile data and rotate the user's Lighthouse token."""
        with self.app.database.connection_context():
            user = User.get_or_none(User.github_id == github_user.id)
            created = user is None
            if user is None:
                user = User(
                    github_id=github_user.id,
                    github_login=github_user.login,
                    display_name=github_user.name,
                    avatar_url=github_user.avatar_url,
                    email=github_user.email,
                )
            else:
                user.github_login = github_user.login
                user.display_name = github_user.name
                user.avatar_url = github_user.avatar_url
                user.email = github_user.email

            api_token = self.generate_api_token()
            user.api_token_hash = self.hash_token(api_token)
            user.api_token_encrypted = self.encrypt_token(api_token)
            user.api_token_issued_at = datetime.now(timezone.utc)
            user.save(force_insert=created)

        return self._to_authenticated_user(user), api_token

    def _revoke_token_sync(self, user_id: str) -> None:
        """Clear the stored bearer-token fields for a user."""
        with self.app.database.connection_context():
            query = User.update(
                api_token_hash=None,
                api_token_encrypted=None,
                api_token_issued_at=None,
            ).where(User.id == user_id)
            query.execute()

    def _to_authenticated_user(self, user: User) -> AuthenticatedUser:
        """Convert a user model into injected authenticated-user context."""
        return AuthenticatedUser(
            id=user.id,
            github_id=user.github_id,
            github_login=user.github_login,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            email=user.email,
            api_token_issued_at=user.api_token_issued_at,
        )
