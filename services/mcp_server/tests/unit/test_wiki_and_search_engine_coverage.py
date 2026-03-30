"""Tests for WikiEngine and SearchEngine covering the missing lines."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mcp_server.engine.search import _discriminate_result_type, _extract_snippets
from mcp_server.engine.wiki import WikiEngine
from mcp_server.utilities.errors import RequestError


# ── _discriminate_result_type ─────────────────────────────────────────────────


@pytest.mark.unit
def test_discriminate_non_dict_returns_code():
    assert _discriminate_result_type("not a dict") == "code"
    assert _discriminate_result_type(None) == "code"
    assert _discriminate_result_type(42) == "code"


@pytest.mark.unit
def test_discriminate_with_explicit_type_field():
    assert _discriminate_result_type({"type": "wiki"}) == "wiki"
    assert _discriminate_result_type({"type": "combined"}) == "combined"


@pytest.mark.unit
def test_discriminate_infers_combined_from_context_source():
    data = {"snippets": [{"context_source": "code", "content": "foo"}]}
    assert _discriminate_result_type(data) == "combined"


@pytest.mark.unit
def test_discriminate_infers_wiki_from_content_snippet():
    data = {"snippets": [{"content_snippet": "a snippet", "slug": "page"}]}
    assert _discriminate_result_type(data) == "wiki"


@pytest.mark.unit
def test_discriminate_empty_snippets_defaults_to_code():
    assert _discriminate_result_type({"snippets": []}) == "code"


# ── _extract_snippets ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_extract_snippets_from_wiki_result():
    data = {
        "type": "wiki",
        "snippets": [
            {
                "page_title": "My Page",
                "slug": "my-page",
                "section_path": "overview",
                "content_snippet": "Some content",
                "score": 0.9,
            }
        ],
        "query": "q",
        "total_results": 1,
    }
    snippets = _extract_snippets(data)
    assert len(snippets) == 1
    assert snippets[0].page_title == "My Page"
    assert snippets[0].slug == "my-page"


@pytest.mark.unit
def test_extract_snippets_from_code_result():
    data = {
        "type": "code",
        "snippets": [
            {
                "file_path": "src/foo.py",
                "start_line": 1,
                "end_line": 10,
                "content": "def foo(): pass",
                "score": 0.8,
            }
        ],
        "query": "q",
        "total_results": 1,
    }
    snippets = _extract_snippets(data)
    assert len(snippets) == 1
    assert snippets[0].file_path == "src/foo.py"


@pytest.mark.unit
def test_extract_snippets_from_combined_result():
    data = {
        "type": "combined",
        "snippets": [
            {
                "context_source": "code",
                "file_path": "src/bar.py",
                "start_line": 5,
                "end_line": 15,
                "content": "class Bar: pass",
                "score": 0.7,
            }
        ],
        "query": "q",
        "total_results": 1,
    }
    snippets = _extract_snippets(data)
    assert len(snippets) == 1
    assert snippets[0].file_path == "src/bar.py"


# ── SearchEngine._map_search_http_error ──────────────────────────────────────


def _make_http_error(status_code: int, json_body: dict | None = None, text: str = "") -> httpx.HTTPStatusError:
    response = httpx.Response(
        status_code=status_code,
        content=(str(json_body) if json_body else text).encode(),
    )
    if json_body is not None:
        import json
        response = httpx.Response(
            status_code=status_code,
            content=json.dumps(json_body).encode(),
            headers={"content-type": "application/json"},
        )
    return httpx.HTTPStatusError("error", request=MagicMock(), response=response)


@pytest.mark.unit
def test_map_search_http_error_404_branch_unavailable():
    from mcp_server.engine.search import SearchEngine

    engine = MagicMock()
    se = SearchEngine(engine)

    exc = _make_http_error(
        404,
        {
            "detail": {
                "error_code": "BRANCH_UNAVAILABLE",
                "message": "Branch not found",
                "context": {"requested_branch": "dev", "indexed_branches": ["main"]},
            }
        },
    )
    err = se._map_search_http_error(exc, "dev")
    assert err.error_code == "BRANCH_UNAVAILABLE"
    assert err.recoverable is True
    assert "dev" in err.context.get("requested_branch", "")


@pytest.mark.unit
def test_map_search_http_error_404_generic():
    from mcp_server.engine.search import SearchEngine

    engine = MagicMock()
    se = SearchEngine(engine)

    exc = _make_http_error(404, {"detail": "Repository not found"})
    err = se._map_search_http_error(exc, "main")
    assert err.error_code == "REPOSITORY_NOT_FOUND_OR_INACCESSIBLE"
    assert err.recoverable is True


@pytest.mark.unit
def test_map_search_http_error_503():
    from mcp_server.engine.search import SearchEngine

    engine = MagicMock()
    se = SearchEngine(engine)

    exc = _make_http_error(503)
    err = se._map_search_http_error(exc, "main")
    assert err.error_code == "UPSTREAM_UNAVAILABLE"
    assert err.recoverable is True


@pytest.mark.unit
def test_map_search_http_error_422():
    from mcp_server.engine.search import SearchEngine

    engine = MagicMock()
    se = SearchEngine(engine)

    exc = _make_http_error(422, {"detail": {"message": "Bad query"}})
    err = se._map_search_http_error(exc, "main")
    assert err.error_code == "INVALID_ARGUMENT"
    assert err.recoverable is True


@pytest.mark.unit
def test_map_search_http_error_non_json_response():
    from mcp_server.engine.search import SearchEngine

    engine = MagicMock()
    se = SearchEngine(engine)

    exc = _make_http_error(500, text="Internal Server Error")
    err = se._map_search_http_error(exc, "main")
    assert err.error_code == "UPSTREAM_ERROR"


# ── WikiEngine ────────────────────────────────────────────────────────────────


def _make_wiki_engine():
    settings = SimpleNamespace(
        ingestion_service_url="http://ingestion",
        search_service_url="http://search",
        internal_service_token="tok",
    )
    db = MagicMock()
    app = SimpleNamespace(settings=settings, database=db)
    engine = SimpleNamespace(app=app)
    return WikiEngine(engine)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_wiki_raises_404_when_repo_not_found(monkeypatch):
    wiki = _make_wiki_engine()
    monkeypatch.setattr(wiki, "_resolve_github_repo_id", lambda _: None)

    with pytest.raises(RequestError) as exc_info:
        await wiki.generate_wiki(
            auth=SimpleNamespace(id="user-1"),
            repository_name="unknown/repo",
            branch="main",
        )
    assert exc_info.value.status_code == 404


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_wiki_returns_accepted_on_success(monkeypatch):
    wiki = _make_wiki_engine()
    monkeypatch.setattr(wiki, "_resolve_github_repo_id", lambda _: 42)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"workflow_id": "wf-123"}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("mcp_server.engine.wiki.httpx.AsyncClient", return_value=mock_client):
        result = await wiki.generate_wiki(
            auth=SimpleNamespace(id="user-1"),
            repository_name="owner/repo",
            branch="main",
        )

    assert result.status == "accepted"
    assert result.workflow_id == "wf-123"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_wiki_raises_502_on_http_error(monkeypatch):
    wiki = _make_wiki_engine()
    monkeypatch.setattr(wiki, "_resolve_github_repo_id", lambda _: 42)

    mock_response = httpx.Response(status_code=500, content=b"error")
    http_error = httpx.HTTPStatusError("fail", request=MagicMock(), response=mock_response)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=http_error)

    with patch("mcp_server.engine.wiki.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RequestError) as exc_info:
            await wiki.generate_wiki(
                auth=SimpleNamespace(id="user-1"),
                repository_name="owner/repo",
                branch="main",
            )
    assert exc_info.value.status_code == 502


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_wiki_raises_502_on_request_error(monkeypatch):
    wiki = _make_wiki_engine()
    monkeypatch.setattr(wiki, "_resolve_github_repo_id", lambda _: 42)

    request_error = httpx.RequestError("connection refused", request=MagicMock())

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=request_error)

    with patch("mcp_server.engine.wiki.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RequestError) as exc_info:
            await wiki.generate_wiki(
                auth=SimpleNamespace(id="user-1"),
                repository_name="owner/repo",
                branch="main",
            )
    assert exc_info.value.status_code == 502


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_wiki_raises_404_when_repo_not_found(monkeypatch):
    wiki = _make_wiki_engine()

    with monkeypatch.context() as mp:
        mp.setattr(
            "db.models.indexing.Repository.get_or_none",
            MagicMock(return_value=None),
        )

        class FakeCtx:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        wiki.engine.app.database.connection_context = MagicMock(return_value=FakeCtx())

        with pytest.raises(RequestError) as exc_info:
            await wiki.get_wiki(
                auth=SimpleNamespace(id="user-1"),
                repository_name="unknown/repo",
                branch="main",
            )
        assert exc_info.value.status_code == 404


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_wiki_raises_404_when_no_completed_generation(monkeypatch):
    wiki = _make_wiki_engine()

    fake_repo = SimpleNamespace(id="repo-1")

    class FakeCtx:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    wiki.engine.app.database.connection_context = MagicMock(return_value=FakeCtx())

    with monkeypatch.context() as mp:
        mp.setattr("db.models.indexing.Repository.get_or_none", MagicMock(return_value=fake_repo))
        gen_query = MagicMock()
        gen_query.where.return_value = gen_query
        gen_query.order_by.return_value = gen_query
        gen_query.first.return_value = None
        mp.setattr("db.models.wiki.WikiGeneration.select", MagicMock(return_value=gen_query))

        with pytest.raises(RequestError) as exc_info:
            await wiki.get_wiki(
                auth=SimpleNamespace(id="user-1"),
                repository_name="owner/repo",
                branch="main",
            )
        assert exc_info.value.status_code == 404


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_wiki_raises_404_when_repo_not_found(monkeypatch):
    wiki = _make_wiki_engine()
    monkeypatch.setattr(wiki, "_resolve_github_repo_id", lambda _: None)

    with pytest.raises(RequestError) as exc_info:
        await wiki.search_wiki(
            auth=SimpleNamespace(id="user-1"),
            repository_name="unknown/repo",
            query="what is this?",
            branch="main",
            top_k=5,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_wiki_returns_results_on_success(monkeypatch):
    wiki = _make_wiki_engine()
    monkeypatch.setattr(wiki, "_resolve_github_repo_id", lambda _: 42)

    mock_result = {
        "snippets": [
            {
                "page_title": "Intro",
                "slug": "intro",
                "section_path": "overview",
                "content_snippet": "Some content",
                "score": 0.9,
            }
        ],
        "query": "what is this?",
        "total_results": 1,
    }

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = mock_result

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("mcp_server.engine.wiki.httpx.AsyncClient", return_value=mock_client):
        result = await wiki.search_wiki(
            auth=SimpleNamespace(id="user-1"),
            repository_name="owner/repo",
            query="what is this?",
            branch="main",
            top_k=5,
        )

    assert result.status == "ok"
    assert len(result.snippets) == 1
    assert result.snippets[0].page_title == "Intro"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_wiki_returns_error_on_http_failure(monkeypatch):
    wiki = _make_wiki_engine()
    monkeypatch.setattr(wiki, "_resolve_github_repo_id", lambda _: 42)

    mock_response = httpx.Response(status_code=500, content=b"error")
    http_error = httpx.HTTPStatusError("fail", request=MagicMock(), response=mock_response)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=http_error)

    with patch("mcp_server.engine.wiki.httpx.AsyncClient", return_value=mock_client):
        result = await wiki.search_wiki(
            auth=SimpleNamespace(id="user-1"),
            repository_name="owner/repo",
            query="what is this?",
            branch="main",
            top_k=5,
        )

    assert result.status == "error"
    assert "500" in result.message


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_wiki_returns_error_on_request_error(monkeypatch):
    wiki = _make_wiki_engine()
    monkeypatch.setattr(wiki, "_resolve_github_repo_id", lambda _: 42)

    request_error = httpx.RequestError("connection refused", request=MagicMock())

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=request_error)

    with patch("mcp_server.engine.wiki.httpx.AsyncClient", return_value=mock_client):
        result = await wiki.search_wiki(
            auth=SimpleNamespace(id="user-1"),
            repository_name="owner/repo",
            query="what is this?",
            branch="main",
            top_k=5,
        )

    assert result.status == "error"
    assert "unavailable" in result.message.lower()


# ── UserEngine ────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_user_engine_add_repo_branches_raises_404_when_not_found(monkeypatch):
    """Cover user.py line 167: repo is None raises 404 in add_user_repo_branches."""
    from unittest.mock import AsyncMock

    from mcp_server.engine.user import AddRepoBranchesRequest, UserEngine
    from mcp_server.utilities.errors import AppError

    authenticator = SimpleNamespace(
        list_visible_private_repository_ids=AsyncMock(return_value=[])
    )
    settings = SimpleNamespace(github_client_id="cid", github_client_secret="csec")
    db = MagicMock()
    app = SimpleNamespace(settings=settings, database=db, authenticator=authenticator)
    engine = SimpleNamespace(app=app)
    ue = UserEngine(engine)

    auth = SimpleNamespace(id="user-1", github_access_token=None)

    monkeypatch.setattr(
        ue, "_get_visible_user_repo_sync", MagicMock(return_value=(None, []))
    )

    with pytest.raises(AppError) as exc_info:
        await ue.add_user_repo_branches(
            auth=auth,
            full_name="unknown/repo",
            request=AddRepoBranchesRequest(branches=["main"]),
        )
    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "REPOSITORY_NOT_FOUND_OR_INACCESSIBLE"


# ── Additional WikiEngine coverage ────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_wiki_returns_response_when_generation_exists(monkeypatch):
    """Lines 119, 261-267: get_wiki succeeds and returns GetWikiResponse."""
    from contextlib import contextmanager

    wiki = _make_wiki_engine()

    @contextmanager
    def fake_ctx():
        yield

    wiki.engine.app.database.connection_context = fake_ctx

    fake_repo = SimpleNamespace(id="repo-1")
    fake_generation = SimpleNamespace(
        id="gen-1",
        wiki_title="My Wiki",
        wiki_description="Overview",
    )
    fake_page = SimpleNamespace(
        slug="auth", title="Auth", content="Auth info", section_path="security"
    )

    with monkeypatch.context() as mp:
        mp.setattr("db.models.indexing.Repository.get_or_none", MagicMock(return_value=fake_repo))
        gen_query = MagicMock()
        gen_query.where.return_value = gen_query
        gen_query.order_by.return_value = gen_query
        gen_query.first.return_value = fake_generation
        mp.setattr("db.models.wiki.WikiGeneration.select", MagicMock(return_value=gen_query))

        page_query = MagicMock()
        page_query.where.return_value = page_query
        page_query.order_by.return_value = [fake_page]
        mp.setattr("db.models.wiki.WikiPage.select", MagicMock(return_value=page_query))

        result = await wiki.get_wiki(
            auth=SimpleNamespace(id="user-1"),
            repository_name="owner/repo",
            branch="main",
        )

    assert result.status == "ok"
    assert result.wiki_title == "My Wiki"
    assert len(result.pages) == 1
    assert result.pages[0].slug == "auth"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_wiki_raises_422_on_validation_error(monkeypatch):
    """Lines 182-183: ValidationError from WikiSearchRequest raises RequestError(422)."""
    wiki = _make_wiki_engine()
    monkeypatch.setattr(wiki, "_resolve_github_repo_id", MagicMock(return_value=42))

    with pytest.raises(RequestError) as exc_info:
        await wiki.search_wiki(
            auth=SimpleNamespace(id="user-1"),
            repository_name="owner/repo",
            query="test query",
            branch="main",
            top_k=0,  # Invalid: must be >= 1
        )
    assert exc_info.value.status_code == 422


@pytest.mark.unit
def test_resolve_github_repo_id_returns_id_when_found(monkeypatch):
    """Lines 232-235: _resolve_github_repo_id returns repo's github_repo_id."""
    from contextlib import contextmanager

    wiki = _make_wiki_engine()

    @contextmanager
    def fake_ctx():
        yield

    wiki.engine.app.database.connection_context = fake_ctx
    fake_repo = SimpleNamespace(github_repo_id=99)

    with monkeypatch.context() as mp:
        mp.setattr("db.models.indexing.Repository.get_or_none", MagicMock(return_value=fake_repo))
        result = wiki._resolve_github_repo_id("owner/repo")
    assert result == 99


@pytest.mark.unit
def test_resolve_github_repo_id_returns_none_when_not_found(monkeypatch):
    """Line 236: _resolve_github_repo_id returns None when repo not found."""
    from contextlib import contextmanager

    wiki = _make_wiki_engine()

    @contextmanager
    def fake_ctx():
        yield

    wiki.engine.app.database.connection_context = fake_ctx

    with monkeypatch.context() as mp:
        mp.setattr("db.models.indexing.Repository.get_or_none", MagicMock(return_value=None))
        result = wiki._resolve_github_repo_id("unknown/repo")
    assert result is None
