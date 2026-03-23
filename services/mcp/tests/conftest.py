from __future__ import annotations

import sys
import types
import uuid
from pathlib import Path

import pytest


SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


def _install_fastmcp_stub() -> None:
    """Install a minimal FastMCP stub so tests can import the MCP app locally."""
    fastmcp_module = types.ModuleType("fastmcp")

    class Context:
        """Placeholder MCP context type for local tests."""

    class _DummySessionManager:
        """Provide the async context-manager hooks used by the app lifespan."""

        def run(self):
            """Return an inert async context manager."""

            class _ContextManager:
                """Implement the async context-manager protocol for tests."""

                async def __aenter__(self):
                    """Enter the no-op async context."""
                    return None

                async def __aexit__(self, exc_type, exc, tb):
                    """Exit the no-op async context."""
                    return False

            return _ContextManager()

    class FastMCP:
        """Minimal FastMCP test double used for handler registration."""

        def __init__(self, *args, **kwargs):
            """Track registered tools and expose a dummy session manager."""
            self.session_manager = _DummySessionManager()
            self.registered_tools = []

        def tool(self):
            """Return a decorator that records the registered tool function."""

            def decorator(fn):
                """Record and return a registered MCP tool."""
                self.registered_tools.append(fn)
                return fn

            return decorator

        def streamable_http_app(self):
            """Return an inert ASGI application for tests."""

            async def app(scope, receive, send):
                """Ignore incoming ASGI calls in the test stub."""
                return None

            return app

    fastmcp_module.Context = Context
    fastmcp_module.FastMCP = FastMCP

    sys.modules["fastmcp"] = fastmcp_module


_install_fastmcp_stub()


from src.models import User, UserRepo  # noqa: E402
from src.utilities import AuthenticatedUser, AuthorizationError  # noqa: E402


@pytest.fixture
def authenticated_user() -> AuthenticatedUser:
    """Return a stable authenticated user context for request tests."""
    return AuthenticatedUser(
        id="user-1",
        github_id=123,
        github_login="octocat",
        display_name="The Octocat",
        avatar_url="https://example.com/octocat.png",
        email="octo@example.com",
        api_token_issued_at=None,
    )


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Return the bearer-auth header used by authenticated request tests."""
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def app_factory(tmp_path):
    """Create isolated app instances with optional sqlite-backed test storage."""
    from src.main import App

    created_apps = []

    def factory(*, with_db: bool = False):
        """Build an app instance and optionally configure a sqlite database."""
        app = App()
        if with_db:
            db_path = tmp_path / f"{uuid.uuid4()}.db"
            app.database.configure(f"sqlite:///{db_path}")
            app.database.connect()
            app.database.database.create_tables([User, UserRepo])
        created_apps.append(app)
        return app

    yield factory

    for app in created_apps:
        if app.database.is_initialized:
            app.database.close()


@pytest.fixture
def install_fake_auth(
    authenticated_user: AuthenticatedUser, auth_headers: dict[str, str]
):
    """Attach deterministic auth resolvers to an app for transport tests."""

    def installer(app):
        """Patch the app authenticator to accept a single test bearer token."""

        async def fake_http_auth(request):
            """Authenticate HTTP calls using the shared test bearer token."""
            if request.headers.get("Authorization") != auth_headers["Authorization"]:
                raise AuthorizationError("Missing Authorization header")
            return authenticated_user

        async def fake_mcp_auth(ctx):
            """Authenticate MCP calls using the shared test bearer token."""
            request = ctx.request_context.request
            header = None if request is None else request.headers.get("Authorization")
            if header != auth_headers["Authorization"]:
                raise AuthorizationError("Missing Authorization header")
            return authenticated_user

        app.authenticator.require_http_request = fake_http_auth
        app.authenticator.require_mcp_context = fake_mcp_auth
        return app

    return installer
