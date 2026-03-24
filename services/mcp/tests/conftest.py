from __future__ import annotations

import hashlib
import sys
import types
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from cryptography.fernet import Fernet


SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


def _install_fastmcp_stub() -> None:
    """Install a minimal FastMCP stub so tests can import the MCP app locally."""
    fastmcp_module = types.ModuleType("fastmcp")

    class Context:
        """Placeholder MCP context type for local tests."""

    class _DummyHTTPApp:
        """Expose the minimal ASGI and lifespan hooks used by the MCP handler."""

        @property
        def lifespan(self):
            """Return an inert async lifespan context factory."""

            @asynccontextmanager
            async def noop_lifespan(app):
                """Yield control without managing any extra startup state."""
                yield None

            return noop_lifespan

        async def __call__(self, scope, receive, send):
            """Ignore incoming ASGI calls in the test stub."""
            return None

    class FastMCP:
        """Minimal FastMCP test double used for handler registration."""

        def __init__(self, *args, **kwargs):
            """Track registered tools and expose a dummy HTTP app."""
            self.registered_tools = []
            self._http_app = _DummyHTTPApp()

        def tool(self):
            """Return a decorator that records the registered tool function."""

            def decorator(fn):
                """Record and return a registered MCP tool."""
                self.registered_tools.append(fn)
                return fn

            return decorator

        def http_app(self, *args, **kwargs):
            """Return an inert HTTP app for the mounted MCP handler."""
            return self._http_app

    fastmcp_module.Context = Context
    fastmcp_module.FastMCP = FastMCP

    sys.modules["fastmcp"] = fastmcp_module


_install_fastmcp_stub()


from src.models import Repository, Session, User, UserHiddenRepository  # noqa: E402
from src.utilities import (  # noqa: E402
    AuthenticatedUser,
    AuthorizationError,
    GitHubRepository,
)


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
        app.settings.session_encryption_key = Fernet.generate_key().decode()
        if with_db:
            db_path = tmp_path / f"{uuid.uuid4()}.db"
            app.database.configure(f"sqlite:///{db_path}")
            app.database.connect()
            app.database.database.create_tables(
                [User, Session, Repository, UserHiddenRepository]
            )
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

        async def fake_fetch_github_repository(
            repo_id: str, *, user_id: str | None = None
        ):
            """Return deterministic repository metadata without calling GitHub."""
            normalized_repo_id = repo_id.lower()
            owner_login, _, repo_name = normalized_repo_id.partition("/")
            github_repo_id = int(
                hashlib.sha1(normalized_repo_id.encode()).hexdigest()[:12], 16
            )
            return GitHubRepository(
                github_repo_id=github_repo_id,
                repo_id=normalized_repo_id,
                repo_url=f"https://github.com/{normalized_repo_id}",
                display_name=normalized_repo_id,
                owner_login=owner_login,
                owner_type="User",
                is_private=False,
            )

        async def fake_list_visible_private_repository_ids(user_id: str):
            """Return no visible private repositories unless a test overrides it."""
            return set()

        app.authenticator.require_http_request = fake_http_auth
        app.authenticator.require_mcp_context = fake_mcp_auth
        app.authenticator.fetch_github_repository = fake_fetch_github_repository
        app.authenticator.list_visible_private_repository_ids = (
            fake_list_visible_private_repository_ids
        )
        return app

    return installer
