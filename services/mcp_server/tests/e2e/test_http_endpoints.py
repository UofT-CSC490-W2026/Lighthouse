import pytest
from unittest.mock import AsyncMock, patch

import httpx
from httpx import ASGITransport
from cryptography.fernet import Fernet

from db import User


@pytest.fixture
def mcp_settings(pg_dsn):
    """Create settings for the MCP server pointing at the test database."""
    from mcp_server.utilities.config.env import Settings

    key = Fernet.generate_key().decode()
    return Settings(
        debug=True,
        cors_allow_origins=["*"],
        postgres_dsn=pg_dsn,
        github_oauth_client_id="test-id",
        github_oauth_client_secret="test-secret",
        github_oauth_callback_url="http://localhost/callback",
        session_encryption_key=key,
        web_client_url="http://localhost:3000",
        session_ttl_hours=24,
        search_service_url="http://localhost:8002",
        ingestion_service_url="http://localhost:8001",
    )


@pytest.fixture
async def client(mcp_settings, db_manager):
    """Create an ASGI test client with routes registered manually.

    httpx's ASGITransport does not invoke ASGI lifespan events, so we
    perform the setup that the lifespan normally handles: connect the
    database and register the HTTP routes.
    """
    from mcp_server.main import App
    from mcp_server.routers.http import HTTPRouteHandler

    app = App(settings=mcp_settings)
    # Use the session-scoped database (already connected by db_manager fixture)
    app.database = db_manager
    # Register routes (normally done inside lifespan)
    http_handler = HTTPRouteHandler(app)
    app.include_router(http_handler.as_router())

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _create_authenticated_user(db_manager, mcp_settings):
    """Create a user with a valid API token and return ``(user, token)``."""
    from mcp_server.utilities.auth import Authenticator
    from unittest.mock import MagicMock

    app_mock = MagicMock()
    app_mock.database = db_manager
    app_mock.settings = mcp_settings
    authenticator = Authenticator(app_mock)

    token = authenticator.generate_api_token()
    token_hash = authenticator.hash_token(token)
    encrypted = authenticator.encrypt_token(token)

    with db_manager.connection_context():
        user = User.create(
            github_id=99999,
            github_login="e2euser",
            display_name="E2E Test User",
            api_token_hash=token_hash,
            api_token_encrypted=encrypted,
        )
    return user, token


@pytest.mark.e2e
class TestMCPServerEndpoints:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_unauthenticated_request(self, client):
        resp = await client.get("/v1/auth/me")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_authenticated_get_me(self, client, db_manager, mcp_settings):
        user, token = _create_authenticated_user(db_manager, mcp_settings)
        resp = await client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["github_login"] == "e2euser"
        assert data["github_id"] == 99999

    @pytest.mark.asyncio
    async def test_authenticated_get_me_missing_bearer(self, client):
        """A request with a malformed Authorization header should be rejected."""
        resp = await client.get(
            "/v1/auth/me",
            headers={"Authorization": "Token abc123"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_authenticated_get_me_invalid_token(self, client):
        """A request with a non-existent token should be rejected."""
        resp = await client.get(
            "/v1/auth/me",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_list_repos_empty(self, client, db_manager, mcp_settings):
        user, token = _create_authenticated_user(db_manager, mcp_settings)

        with patch(
            "mcp_server.utilities.auth.Authenticator.list_visible_private_repository_ids",
            new_callable=AsyncMock,
            return_value=set(),
        ):
            resp = await client.get(
                "/v1/user/repos",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_logout(self, client, db_manager, mcp_settings):
        user, token = _create_authenticated_user(db_manager, mcp_settings)

        # Verify the token works first
        resp = await client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        # Logout (revoke the token)
        resp = await client.post(
            "/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204

        # The token should now be invalid
        resp = await client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_github_authorize_redirect(self, client):
        """The GitHub OAuth authorize endpoint should redirect to GitHub."""
        resp = await client.get("/v1/auth/github", follow_redirects=False)
        assert resp.status_code == 307
        assert "github.com/login/oauth/authorize" in resp.headers["location"]

    @pytest.mark.asyncio
    async def test_mcp_token_lifecycle(self, client, db_manager, mcp_settings):
        """Rotate, retrieve, and revoke an MCP token through the HTTP API."""
        user, token = _create_authenticated_user(db_manager, mcp_settings)
        headers = {"Authorization": f"Bearer {token}"}

        # Initially no MCP token
        resp = await client.get("/v1/auth/mcp-token", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_token"] is False
        assert data["token"] is None

        # Rotate (create) an MCP token
        resp = await client.post("/v1/auth/mcp-token", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_token"] is True
        assert data["token"] is not None
        mcp_token = data["token"]

        # Retrieve the MCP token
        resp = await client.get("/v1/auth/mcp-token", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_token"] is True
        assert data["token"] == mcp_token

        # Revoke the MCP token
        resp = await client.delete("/v1/auth/mcp-token", headers=headers)
        assert resp.status_code == 204

        # Confirm it's gone
        resp = await client.get("/v1/auth/mcp-token", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_token"] is False
        assert data["token"] is None
