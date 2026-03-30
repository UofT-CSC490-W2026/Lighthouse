from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import Request

from db import IndexedBranch, Repository, Session, User
from mcp_server.engine.auth import AuthEngine
from mcp_server.engine.search import SearchEngine
from mcp_server.engine.user import AddRepoBranchesRequest, AddUserRepoRequest, UserEngine
from mcp_server.main import App
from mcp_server.utilities.auth import (
    AuthenticatedUser,
    Authenticator,
    AuthorizationError,
    GitHubRepository,
    GitHubUser,
    ManagedToken,
    RequestError,
)
from shared.schemas.search import CodeSnippet
from mcp_server.utilities.config.env import reload_settings


def _make_authenticator(db_manager):
    key = Fernet.generate_key().decode()
    app = MagicMock()
    app.database = db_manager
    app.settings.session_encryption_key = key
    app.settings.github_oauth_client_id = "client-id"
    app.settings.github_oauth_client_secret = "client-secret"
    app.settings.github_oauth_callback_url = "http://localhost/callback"
    app.settings.web_client_url = "http://localhost:3000/"
    return Authenticator(app)


class _Response:
    def __init__(self, *, status_code=200, json_data=None, text="text"):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.request = httpx.Request("GET", "http://test")

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=self.request, response=self)


class _AsyncClient:
    def __init__(self, *, post_response=None, get_response=None, post_error=None):
        self._post_response = post_response
        self._get_response = get_response
        self._post_error = post_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        if self._post_error:
            raise self._post_error
        return self._post_response

    async def get(self, *args, **kwargs):
        return self._get_response


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticator_async_helpers_and_http_paths(db_manager, monkeypatch):
    auth = _make_authenticator(db_manager)
    github_user = GitHubUser(id=123, login="octo", name="Octo", avatar_url=None, email=None)
    authed_user, token = auth._upsert_github_user_and_issue_token_sync(github_user, "gh-token")

    request = MagicMock(spec=Request)
    request.headers = {"Authorization": f"Bearer {token}"}
    assert (await auth.require_http_request(request)).id == authed_user.id

    ctx = SimpleNamespace(request_context=SimpleNamespace(request=request))
    assert (await auth.require_mcp_context(ctx)).id == authed_user.id

    with pytest.raises(AuthorizationError, match="Request context is unavailable"):
        await auth.require_mcp_context(SimpleNamespace(request_context=SimpleNamespace(request=None)))

    assert (await auth.authenticate_bearer_token(token)).id == authed_user.id
    assert (await auth.get_mcp_token(authed_user.id)).token is None
    rotated = await auth.rotate_mcp_token(authed_user.id)
    assert rotated.token is not None
    await auth.revoke_mcp_token(authed_user.id)
    await auth.revoke_token(authed_user.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticator_github_api_paths(db_manager, monkeypatch):
    auth = _make_authenticator(db_manager)
    gh_user = GitHubUser(id=777, login="user", name=None, avatar_url=None, email=None)
    authed_user, _ = auth._upsert_github_user_and_issue_token_sync(gh_user, "access-token")

    monkeypatch.setattr(
        "mcp_server.utilities.auth.httpx.AsyncClient",
        lambda *args, **kwargs: _AsyncClient(post_response=_Response(json_data={"access_token": "token"})),
    )
    assert await auth.exchange_code_for_token("code") == "token"

    monkeypatch.setattr(
        "mcp_server.utilities.auth.httpx.AsyncClient",
        lambda *args, **kwargs: _AsyncClient(post_response=_Response(json_data={"error": "bad", "error_description": "denied"})),
    )
    with pytest.raises(RuntimeError, match="denied"):
        await auth.exchange_code_for_token("code")

    monkeypatch.setattr(
        "mcp_server.utilities.auth.httpx.AsyncClient",
        lambda *args, **kwargs: _AsyncClient(get_response=_Response(json_data={"id": 1, "login": "octo"})),
    )
    assert (await auth.fetch_github_user("access")).login == "octo"

    monkeypatch.setattr(
        "mcp_server.utilities.auth.httpx.AsyncClient",
        lambda *args, **kwargs: _AsyncClient(get_response=_Response(status_code=404)),
    )
    with pytest.raises(RequestError, match="does not exist"):
        await auth.fetch_github_repository("owner/repo")

    monkeypatch.setattr(
        "mcp_server.utilities.auth.httpx.AsyncClient",
        lambda *args, **kwargs: _AsyncClient(get_response=_Response(status_code=403)),
    )
    with pytest.raises(RequestError, match="could not verify"):
        await auth.fetch_github_repository("owner/repo", user_id=authed_user.id)

    monkeypatch.setattr(
        "mcp_server.utilities.auth.httpx.AsyncClient",
        lambda *args, **kwargs: _AsyncClient(
            get_response=_Response(
                json_data={
                    "id": 9,
                    "full_name": "Owner/Repo",
                    "html_url": "https://github.com/Owner/Repo",
                    "owner": {},
                    "private": True,
                }
            )
        ),
    )
    repo = await auth.fetch_github_repository("owner/repo", user_id=authed_user.id)
    assert repo.owner_login == "owner"
    assert repo.default_branch == "main"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticator_private_repo_listing_and_sync_edges(db_manager, monkeypatch):
    auth = _make_authenticator(db_manager)
    gh_user = GitHubUser(id=888, login="user", name=None, avatar_url=None, email=None)
    authed_user, token = auth._upsert_github_user_and_issue_token_sync(gh_user, "access-token")

    monkeypatch.setattr(auth, "_get_github_access_token_sync", MagicMock(return_value=None))
    assert await auth.list_visible_private_repository_ids(authed_user.id) == set()

    monkeypatch.setattr(auth, "_get_github_access_token_sync", MagicMock(return_value="access-token"))
    responses = [
        _Response(status_code=403),
    ]

    class Client403(_AsyncClient):
        async def get(self, *args, **kwargs):
            return responses.pop(0)

    monkeypatch.setattr("mcp_server.utilities.auth.httpx.AsyncClient", lambda *args, **kwargs: Client403())
    assert await auth.list_visible_private_repository_ids(authed_user.id) == set()

    pages = [
        _Response(json_data=[{"id": 1}] * 100),
        _Response(json_data=[{"id": 2}, {"id": None}]),
    ]

    class ClientPages(_AsyncClient):
        async def get(self, *args, **kwargs):
            return pages.pop(0)

    monkeypatch.setattr("mcp_server.utilities.auth.httpx.AsyncClient", lambda *args, **kwargs: ClientPages())
    assert await auth.list_visible_private_repository_ids(authed_user.id) == {1, 2}

    pages = [_Response(json_data=[])]

    class ClientEmpty(_AsyncClient):
        async def get(self, *args, **kwargs):
            return pages.pop(0)

    monkeypatch.setattr("mcp_server.utilities.auth.httpx.AsyncClient", lambda *args, **kwargs: ClientEmpty())
    assert await auth.list_visible_private_repository_ids(authed_user.id) == set()

    monkeypatch.undo()
    with db_manager.connection_context():
        Session.update(expires_at=datetime.now(timezone.utc) - timedelta(days=1)).execute()
    assert auth._get_github_access_token_sync(authed_user.id) is None

    with db_manager.connection_context():
        auth._upsert_github_session_sync(authed_user.id, "fresh-token")
    assert auth._get_github_access_token_sync(authed_user.id) == "fresh-token"

    with pytest.raises(AuthorizationError):
        auth._get_mcp_token_sync("missing-user")
    with pytest.raises(AuthorizationError):
        auth._rotate_mcp_token_sync("missing-user")

    with db_manager.connection_context():
        user = User.get(User.id == authed_user.id)
        user.api_token_hash = auth.hash_token(token)
        user.api_token_encrypted = auth.encrypt_token("different-token")
        user.save()
    with pytest.raises(AuthorizationError):
        auth._authenticate_bearer_token_sync(token)

    assert auth.build_oauth_success_redirect("abc") == "http://localhost:3000/auth/callback#token=abc"
    assert auth.build_oauth_error_redirect("bad") == "http://localhost:3000/login?error=bad"


@pytest.mark.unit
def test_reload_settings_clears_caches(monkeypatch):
    get_settings_mock = MagicMock(return_value="settings")
    get_settings_mock.cache_clear = MagicMock()
    get_ssm_client_mock = MagicMock()
    get_ssm_client_mock.cache_clear = MagicMock()
    get_parameter_value_mock = MagicMock()
    get_parameter_value_mock.cache_clear = MagicMock()

    monkeypatch.setattr("mcp_server.utilities.config.env.get_settings", get_settings_mock)
    monkeypatch.setattr("mcp_server.utilities.config.env.get_ssm_client", get_ssm_client_mock)
    monkeypatch.setattr("mcp_server.utilities.config.env._get_parameter_value", get_parameter_value_mock)

    assert reload_settings() == "settings"
    get_settings_mock.cache_clear.assert_called_once_with()
    get_ssm_client_mock.cache_clear.assert_called_once_with()
    get_parameter_value_mock.cache_clear.assert_called_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_auth_engine_covers_redirect_and_logout_paths(monkeypatch):
    auth = AuthenticatedUser(id="u", github_id=1, github_login="octo", display_name=None, avatar_url=None, email=None, authenticated_via="mcp")
    authenticator = SimpleNamespace(
        generate_state=MagicMock(return_value="state"),
        build_authorize_url=MagicMock(return_value="http://github"),
        build_oauth_error_redirect=MagicMock(return_value="http://error"),
        build_oauth_success_redirect=MagicMock(return_value="http://success"),
        exchange_code_for_token=AsyncMock(side_effect=RuntimeError("boom")),
        fetch_github_user=AsyncMock(),
        upsert_github_user_and_issue_token=AsyncMock(),
        revoke_mcp_token=AsyncMock(),
        revoke_token=AsyncMock(),
        get_mcp_token=AsyncMock(return_value=ManagedToken(token=None, issued_at=None)),
        rotate_mcp_token=AsyncMock(return_value=ManagedToken(token="mcp", issued_at=None)),
    )
    engine = AuthEngine(SimpleNamespace(app=SimpleNamespace(authenticator=authenticator, settings=SimpleNamespace(debug=False))))

    response = engine.github_authorize()
    assert response.status_code == 307

    request = MagicMock()
    request.cookies = {"oauth_state": "expected"}
    response = await engine.github_callback(request, code="abc", state="wrong")
    assert response.headers["location"] == "http://error"

    response = await engine.github_callback(request, code="abc", state="expected")
    assert response.headers["location"] == "http://error"

    authenticator.exchange_code_for_token = AsyncMock(return_value="access-token")
    authenticator.fetch_github_user = AsyncMock(return_value=GitHubUser(id=1, login="octo", name=None, avatar_url=None, email=None))
    authenticator.upsert_github_user_and_issue_token = AsyncMock(return_value=(auth, "api-token"))
    response = await engine.github_callback(request, code="abc", state="expected")
    assert response.headers["location"] == "http://success"

    assert (await engine.logout(auth)).status_code == 204
    authenticator.revoke_mcp_token.assert_awaited_once_with("u")

    auth = AuthenticatedUser(id="u2", github_id=1, github_login="octo", display_name=None, avatar_url=None, email=None)
    assert (await engine.logout(auth)).status_code == 204
    authenticator.revoke_token.assert_awaited_once_with("u2")
    assert (await engine.get_mcp_token(auth)).has_token is False
    assert (await engine.rotate_mcp_token(auth)).token == "mcp"
    assert (await engine.revoke_mcp_token(auth)).status_code == 204


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_and_user_engines_cover_error_paths(monkeypatch):
    auth = AuthenticatedUser(id="user-1", github_id=1, github_login="octo", display_name=None, avatar_url=None, email=None)
    app = SimpleNamespace(
        settings=SimpleNamespace(search_service_url="http://search", ingestion_service_url="http://ingest", internal_service_token=""),
        database=SimpleNamespace(connection_context=contextmanager(lambda: (yield))()),
        authenticator=SimpleNamespace(
            list_visible_private_repository_ids=AsyncMock(return_value={11}),
            fetch_github_repository=AsyncMock(
                return_value=GitHubRepository(
                    github_repo_id=11,
                    full_name="owner/repo",
                    repo_url="https://github.com/owner/repo",
                    display_name="owner/repo",
                    owner_login="owner",
                    owner_type="User",
                    is_private=False,
                    default_branch="main",
                )
            ),
            _get_github_access_token_sync=MagicMock(return_value="gh-token"),
        ),
    )
    engine_root = SimpleNamespace(app=app)
    search_engine = SearchEngine(engine_root)
    user_engine = UserEngine(engine_root)

    monkeypatch.setattr(search_engine, "_resolve_github_repo_id", MagicMock(return_value=None))
    with pytest.raises(RequestError, match="not found"):
        await search_engine.get_code_context(auth, " owner/repo ", "fix bug")

    monkeypatch.setattr(search_engine, "_resolve_github_repo_id", MagicMock(return_value=11))
    with pytest.raises(RequestError, match="query is required"):
        await search_engine.get_code_context(auth, "owner/repo", "   ")
    validation_error = Exception()
    monkeypatch.setattr(
        "mcp_server.engine.search.SearchRequest",
        MagicMock(side_effect=validation_error),
    )
    monkeypatch.setattr("mcp_server.engine.search.ValidationError", Exception)
    with pytest.raises(RequestError):
        await search_engine.get_code_context(auth, "owner/repo", "fix bug")
    monkeypatch.undo()
    monkeypatch.setattr(search_engine, "_resolve_github_repo_id", MagicMock(return_value=11))

    http_status = httpx.HTTPStatusError(
        "bad",
        request=httpx.Request("POST", "http://search/search"),
        response=httpx.Response(500, text="oops"),
    )
    monkeypatch.setattr("mcp_server.engine.search.httpx.AsyncClient", lambda *args, **kwargs: _AsyncClient(post_error=http_status))
    result = await search_engine.get_code_context(auth, "owner/repo", "fix bug")
    assert result.status == "error"

    monkeypatch.setattr(
        "mcp_server.engine.search.httpx.AsyncClient",
        lambda *args, **kwargs: _AsyncClient(post_error=httpx.RequestError("down", request=httpx.Request("POST", "http://search"))),
    )
    result = await search_engine.get_code_context(auth, "owner/repo", "fix bug")
    assert result.message == "Search service unavailable."

    monkeypatch.setattr(
        "mcp_server.engine.search.httpx.AsyncClient",
        lambda *args, **kwargs: _AsyncClient(
            post_response=_Response(
                json_data={
                    "snippets": [
                        {
                            "file_path": "a.py",
                            "start_line": 1,
                            "end_line": 2,
                            "content": "print('hi')",
                            "language": "python",
                            "score": 0.9,
                            "reason": "relevant",
                        }
                    ],
                    "query": "fix bug",
                    "total_results": 1,
                }
            )
        ),
    )
    captured_request: dict[str, object] = {}

    class _CapturingAsyncClient(_AsyncClient):
        async def post(self, *args, **kwargs):
            captured_request.update(kwargs["json"])
            return await super().post(*args, **kwargs)

    monkeypatch.setattr(
        "mcp_server.engine.search.httpx.AsyncClient",
        lambda *args, **kwargs: _CapturingAsyncClient(
            post_response=_Response(
                json_data={
                    "snippets": [
                        {
                            "file_path": "a.py",
                            "start_line": 1,
                            "end_line": 2,
                            "content": "print('hi')",
                            "language": "python",
                            "score": 0.9,
                            "reason": "relevant",
                        }
                    ],
                    "query": "fix bug",
                    "total_results": 1,
                }
            )
        ),
    )

    result = await search_engine.get_code_context(
        auth,
        " owner/repo ",
        "fix bug",
        file_path=" a.py ",
    )
    assert captured_request == {
        "query": "fix bug",
        "github_repo_id": 11,
        "branch": "main",
        "file_path": "a.py",
        "top_k": 10,
    }
    assert result.status == "ok"
    assert result.query == "fix bug"
    assert result.snippets[0].reason == "relevant"

    monkeypatch.setattr(user_engine, "_list_user_repos_sync", MagicMock(return_value=[]))
    assert await user_engine.list_user_repos(auth) == []

    created_repo = SimpleNamespace(
        id="repo-1",
        github_repo_id=11,
        full_name="owner/repo",
        repo_url="https://github.com/owner/repo",
        display_name="owner/repo",
        added_at=datetime.now(timezone.utc),
    )
    upsert_mock = MagicMock(return_value=(created_repo, True))
    monkeypatch.setattr(user_engine, "_upsert_user_repo_sync", upsert_mock)
    trigger_mock = AsyncMock()
    monkeypatch.setattr(user_engine, "_trigger_ingestion", trigger_mock)
    assert (
        await user_engine.add_user_repo(
            auth,
            AddUserRepoRequest(
                repo_url="https://github.com/Owner/Repo.git",
                branches=[" release ", "main", "", "release"],
            ),
        )
    ).full_name == "owner/repo"
    trigger_mock.assert_awaited_once()
    trigger_mock.assert_awaited_with(
        user_engine.engine.app.authenticator.fetch_github_repository.return_value,
        "user-1",
        ["main", "release"],
    )

    upsert_mock.return_value = (created_repo, False)
    trigger_mock.reset_mock()
    assert (
        await user_engine.add_user_repo(
            auth,
            AddUserRepoRequest(repo_url="https://github.com/Owner/Repo.git"),
        )
    ).full_name == "owner/repo"
    trigger_mock.assert_not_called()

    indexed_branches = [
        SimpleNamespace(branch_name="main", status="indexed"),
        SimpleNamespace(branch_name="dev", status="indexed"),
    ]
    monkeypatch.setattr(
        user_engine.engine.app.authenticator,
        "list_visible_private_repository_ids",
        AsyncMock(return_value=set()),
    )
    trigger_mock.reset_mock()
    refreshed_repo = SimpleNamespace(**created_repo.__dict__)
    monkeypatch.setattr(
        user_engine,
        "_get_visible_user_repo_sync",
        MagicMock(side_effect=[(created_repo, indexed_branches), (refreshed_repo, indexed_branches)]),
    )
    assert (
        await user_engine.add_user_repo_branches(
            auth,
            "owner/repo",
            AddRepoBranchesRequest(branches=[" dev ", "release", "", "release"]),
        )
    ).full_name == "owner/repo"
    trigger_mock.assert_awaited_with(
        user_engine.engine.app.authenticator.fetch_github_repository.return_value,
        "user-1",
        ["release"],
    )
    monkeypatch.setattr(
        user_engine,
        "_get_visible_user_repo_sync",
        MagicMock(return_value=(created_repo, indexed_branches)),
    )

    with pytest.raises(RequestError, match="At least one branch is required"):
        await user_engine.add_user_repo_branches(
            auth,
            "owner/repo",
            AddRepoBranchesRequest(branches=[" ", ""]),
        )

    with pytest.raises(RequestError, match="already indexed"):
        await user_engine.add_user_repo_branches(
            auth,
            "owner/repo",
            AddRepoBranchesRequest(branches=["main", "dev", "main"]),
        )

    monkeypatch.setattr(user_engine, "_hide_user_repo_sync", MagicMock(return_value=False))
    assert (await user_engine.remove_user_repo(auth, "owner/repo")).hidden is False

    with pytest.raises(RequestError, match="Only github.com repositories are supported"):
        user_engine._normalize_full_name("https://gitlab.com/owner/repo")

    with pytest.raises(RequestError, match="Repository must be in owner/repo form"):
        user_engine._normalize_full_name("owner")

    with pytest.raises(RequestError, match="Repository is required"):
        user_engine._normalize_full_name("  ")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_user_engine_trigger_ingestion_service_errors():
    repo = GitHubRepository(
        github_repo_id=11,
        full_name="owner/repo",
        repo_url="https://github.com/owner/repo",
        display_name="owner/repo",
        owner_login="owner",
        owner_type="User",
        is_private=False,
        default_branch="main",
    )
    app = SimpleNamespace(
        settings=SimpleNamespace(ingestion_service_url="http://ingest", internal_service_token=""),
        authenticator=SimpleNamespace(_get_github_access_token_sync=MagicMock(return_value="gh-token")),
    )
    engine = UserEngine(SimpleNamespace(app=app))

    status_error = httpx.HTTPStatusError(
        "bad",
        request=httpx.Request("POST", "http://ingest/index"),
        response=httpx.Response(502, text="oops"),
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("mcp_server.engine.user.httpx.AsyncClient", lambda *args, **kwargs: _AsyncClient(post_error=status_error))
    with pytest.raises(RequestError, match="Ingestion service error: 502"):
        await engine._trigger_ingestion(repo, "user-1", ["main"])

    monkeypatch.setattr(
        "mcp_server.engine.user.httpx.AsyncClient",
        lambda *args, **kwargs: _AsyncClient(post_error=httpx.RequestError("down", request=httpx.Request("POST", "http://ingest"))),
    )
    with pytest.raises(RequestError, match="Ingestion service unavailable"):
        await engine._trigger_ingestion(repo, "user-1", ["main"])
    monkeypatch.undo()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_user_engine_trigger_ingestion_success_and_search_resolve_none(db_manager, monkeypatch):
    repo = GitHubRepository(
        github_repo_id=11,
        full_name="owner/repo",
        repo_url="https://github.com/owner/repo",
        display_name="owner/repo",
        owner_login="owner",
        owner_type="User",
        is_private=False,
        default_branch="main",
    )
    app = SimpleNamespace(
        settings=SimpleNamespace(ingestion_service_url="http://ingest", internal_service_token=""),
        authenticator=SimpleNamespace(_get_github_access_token_sync=MagicMock(return_value="gh-token")),
        database=db_manager,
    )
    user_engine = UserEngine(SimpleNamespace(app=app))
    monkeypatch.setattr(
        "mcp_server.engine.user.httpx.AsyncClient",
        lambda *args, **kwargs: _AsyncClient(post_response=_Response(json_data={"status": "accepted", "workflow_ids": ["wf-1"]})),
    )
    result = await user_engine._trigger_ingestion(repo, "user-1", ["main", "release"])
    assert result.workflow_ids == ["wf-1"]

    search_engine = SearchEngine(SimpleNamespace(app=SimpleNamespace(database=db_manager)))
    assert search_engine._resolve_github_repo_id("missing/repo") is None


@pytest.mark.integration
def test_search_and_user_engine_sync_db_paths(db_manager):
    app = SimpleNamespace(
        database=db_manager,
        settings=SimpleNamespace(search_service_url="http://search", ingestion_service_url="http://ingest"),
        authenticator=SimpleNamespace(),
    )
    search_engine = SearchEngine(SimpleNamespace(app=app))
    user_engine = UserEngine(SimpleNamespace(app=app))
    with db_manager.connection_context():
        User.create(id="user-1", github_id=1, github_login="user-1")

    github_repo = GitHubRepository(
        github_repo_id=55,
        full_name="owner/repo",
        repo_url="https://github.com/owner/repo",
        display_name="owner/repo",
        owner_login="owner",
        owner_type="User",
        is_private=False,
        default_branch="main",
    )

    repo, needs_ingestion = user_engine._upsert_user_repo_sync(github_repo, "user-1")
    assert repo.full_name == "owner/repo"
    assert needs_ingestion is True

    updated, needs_again = user_engine._upsert_user_repo_sync(
        GitHubRepository(
            github_repo_id=55,
            full_name="owner/repo",
            repo_url="https://github.com/owner/repo",
            display_name="Owner Repo",
            owner_login="owner",
            owner_type="Organization",
            is_private=True,
            default_branch="main",
        ),
        "user-1",
    )
    assert updated.display_name == "Owner Repo"
    assert needs_again is True

    assert user_engine._hide_user_repo_sync("user-1", "missing/repo") is False
    assert user_engine._hide_user_repo_sync("user-1", "owner/repo") is True
    assert user_engine._hide_user_repo_sync("user-1", "owner/repo") is False
    assert user_engine._list_user_repos_sync("user-1", set()) == []

    _, needs_after_unhide = user_engine._upsert_user_repo_sync(github_repo, "user-1")
    assert needs_after_unhide is False
    visible = user_engine._list_user_repos_sync("user-1", {55})
    assert len(visible) == 1
    repo_obj, branches = visible[0]
    assert user_engine._to_user_repo_response(repo_obj, branches).index_status is None
    found_repo, found_branches = user_engine._get_visible_user_repo_sync("user-1", "owner/repo", {55})
    assert found_repo is not None
    assert found_branches == []
    missing_repo, missing_branches = user_engine._get_visible_user_repo_sync("user-1", "missing/repo", {55})
    assert missing_repo is None
    assert missing_branches == []

    # Add indexed branches and verify they are returned and status is computed correctly
    with db_manager.connection_context():
        IndexedBranch.create(repository=repo_obj, branch_name="main", status="indexed")
        IndexedBranch.create(repository=repo_obj, branch_name="dev", status="indexing")

    visible = user_engine._list_user_repos_sync("user-1", {55})
    repo_obj, branches = visible[0]
    assert len(branches) == 2
    branch_names = [b.branch_name for b in branches]
    assert "main" in branch_names and "dev" in branch_names

    response = user_engine._to_user_repo_response(repo_obj, branches)
    assert response.index_status == "INDEXING"
    assert len(response.branches) == 2
    assert all(b.status == b.status.upper() for b in response.branches)

    assert search_engine._resolve_github_repo_id("owner/repo") == 55
    with pytest.raises(RequestError, match="owner/repo form"):
        user_engine._normalize_full_name("owner/   ")
    with pytest.raises(RequestError, match="owner/repo form"):
        user_engine._normalize_full_name("owner/.git")
    assert user_engine._normalize_branch_names([" main ", "", "release", "main"]) == ["main", "release"]
    assert user_engine._merge_default_branch("main", ["release", "main", "dev"]) == ["main", "release", "dev"]


@pytest.mark.unit
def test_compute_index_status():
    from mcp_server.engine.user import BranchInfo

    engine = UserEngine(MagicMock())

    assert engine._compute_index_status([]) is None

    def make(status):
        return BranchInfo(branch_name="b", status=status)

    assert engine._compute_index_status([make("INDEXED")]) == "INDEXED"
    assert engine._compute_index_status([make("INDEXING")]) == "INDEXING"
    assert engine._compute_index_status([make("PENDING")]) == "PENDING"
    assert engine._compute_index_status([make("FAILED")]) == "FAILED"

    # Priority: INDEXING > PENDING > FAILED > INDEXED
    assert engine._compute_index_status([make("INDEXED"), make("INDEXING")]) == "INDEXING"
    assert engine._compute_index_status([make("INDEXED"), make("PENDING")]) == "PENDING"
    assert engine._compute_index_status([make("INDEXED"), make("FAILED")]) == "FAILED"
    assert engine._compute_index_status([make("FAILED"), make("INDEXING")]) == "INDEXING"

    # Fallback: bypass Pydantic to hit the unreachable default branch
    unknown = BranchInfo.model_construct(branch_name="b", status="UNKNOWN")
    assert engine._compute_index_status([unknown]) == "UNKNOWN"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_authenticator_configuration_and_async_upsert(db_manager, monkeypatch):
    auth = _make_authenticator(db_manager)
    auth.app.settings.github_oauth_client_id = None
    with pytest.raises(RuntimeError, match="GITHUB_OAUTH_CLIENT_ID is required"):
        auth.build_authorize_url("state")
    with pytest.raises(RuntimeError, match="GITHUB_OAUTH_CLIENT_ID is required"):
        await auth.exchange_code_for_token("code")

    auth.app.settings.github_oauth_client_id = "client-id"
    auth.app.settings.github_oauth_client_secret = None
    with pytest.raises(RuntimeError, match="GITHUB_OAUTH_CLIENT_SECRET is required"):
        await auth.exchange_code_for_token("code")

    auth.app.settings.github_oauth_client_secret = "client-secret"
    monkeypatch.setattr("mcp_server.utilities.auth.httpx.AsyncClient", lambda *args, **kwargs: _AsyncClient(post_response=_Response(json_data={})))
    with pytest.raises(RuntimeError, match="No access_token"):
        await auth.exchange_code_for_token("code")

    auth.app.settings.session_encryption_key = None
    with pytest.raises(RuntimeError, match="SESSION_ENCRYPTION_KEY is required"):
        auth.encrypt_token("token")

    auth = _make_authenticator(db_manager)
    github_user = GitHubUser(id=999, login="user", name=None, avatar_url=None, email=None)
    authed_user, token = await auth.upsert_github_user_and_issue_token(github_user, "gh-token")
    assert authed_user.github_login == "user"
    assert token


@pytest.mark.unit
@pytest.mark.asyncio
async def test_app_lifespan_success_and_failure(monkeypatch):
    settings = SimpleNamespace(
        postgres_dsn="postgres://db",
        cors_allow_origins=["*"],
        github_oauth_client_id="id",
        github_oauth_client_secret="secret",
        github_oauth_callback_url="http://callback",
        session_encryption_key=Fernet.generate_key().decode(),
        web_client_url="http://web",
        session_ttl_hours=1,
        search_service_url="http://search",
        ingestion_service_url="http://ingest",
        debug=True,
    )
    app = App(settings=settings)
    app.database = MagicMock(is_configured=True)
    http_handler = MagicMock()
    http_handler.as_router.return_value = "router"
    mcp_handler = MagicMock(startup=AsyncMock(), shutdown=AsyncMock())

    monkeypatch.setattr("mcp_server.main.HTTPRouteHandler", MagicMock(return_value=http_handler))
    monkeypatch.setattr("mcp_server.main.MCPToolHandler", MagicMock(return_value=mcp_handler))
    app.include_router = MagicMock()
    app.mount = MagicMock()

    async with app.lifespan():
        pass

    app.database.connect.assert_called_once_with()
    app.include_router.assert_called_once_with("router")
    app.mount.assert_called_once_with("/mcp", mcp_handler)
    mcp_handler.startup.assert_awaited_once()
    mcp_handler.shutdown.assert_awaited_once()
    app.database.close.assert_called_once_with()

    app = App(settings=settings)
    app.database = MagicMock(is_configured=False)
    http_handler = MagicMock()
    http_handler.as_router.return_value = "router"
    mcp_handler = MagicMock(startup=AsyncMock(side_effect=RuntimeError("boom")), shutdown=AsyncMock())

    monkeypatch.setattr("mcp_server.main.HTTPRouteHandler", MagicMock(return_value=http_handler))
    monkeypatch.setattr("mcp_server.main.MCPToolHandler", MagicMock(return_value=mcp_handler))
    app.include_router = MagicMock()
    app.mount = MagicMock()

    with pytest.raises(RuntimeError, match="Failed to initialize server state"):
        async with app.lifespan():
            pass
