from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.models import User, UserRepo
from src.routers.mcp.handler import MCPToolHandler
from src.utilities import collect_toolcalls


def test_health_is_public_and_current_user_requires_auth(app_factory) -> None:
    """Verify the public health endpoint and protected current-user route."""
    app = app_factory()

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"ok": True}

        current_user = client.get("/v1/auth/me")
        assert current_user.status_code == 401
        assert current_user.json() == {"detail": "Missing Authorization header"}


def test_get_code_context_http_returns_placeholder(
    app_factory,
    install_fake_auth,
    auth_headers,
    authenticated_user,
) -> None:
    """Ensure the HTTP search entrypoint returns the current placeholder envelope."""
    app = install_fake_auth(app_factory())

    with TestClient(app) as client:
        response = client.post(
            "/v1/search/code-context",
            headers=auth_headers,
            json={
                "repository_name": "openai/openai-python",
                "task_description": "Need context for a parser bug fix",
                "branch": "main",
                "latest_commit": "abc123",
                "file_path": "src/parser.py",
                "start_line": 10,
                "end_line": 20,
                "selected_text": "def parse(): ...",
                "surrounding_context": "Parser is failing on empty input.",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "not_implemented",
        "message": (
            "Code context retrieval is not implemented yet. "
            "This placeholder captures the request envelope for future search work."
        ),
        "repository_name": "openai/openai-python",
        "branch": "main",
        "latest_commit": "abc123",
        "task_description": "Need context for a parser bug fix",
        "requested_by_user_id": authenticated_user.id,
        "highlight": {
            "file_path": "src/parser.py",
            "start_line": 10,
            "end_line": 20,
            "selected_text": "def parse(): ...",
            "surrounding_context": "Parser is failing on empty input.",
        },
        "snippets": [],
        "follow_up": [],
    }


def test_get_code_context_rejects_invalid_line_ranges(
    app_factory,
    install_fake_auth,
    auth_headers,
) -> None:
    """Return a client error when the highlighted line range is inconsistent."""
    app = install_fake_auth(app_factory())

    with TestClient(app) as client:
        response = client.post(
            "/v1/search/code-context",
            headers=auth_headers,
            json={
                "repository_name": "openai/openai-python",
                "task_description": "Need context for a parser bug fix",
                "end_line": 20,
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "start_line is required when end_line is provided."
    }


def test_user_repo_http_lifecycle(
    app_factory,
    install_fake_auth,
    auth_headers,
    authenticated_user,
) -> None:
    """Add, soft-delete, and restore a user repository through the HTTP API."""
    app = install_fake_auth(app_factory(with_db=True))
    with app.database.connection_context():
        User.create(
            id=authenticated_user.id,
            github_id=authenticated_user.github_id,
            github_login=authenticated_user.github_login,
            display_name=authenticated_user.display_name,
            avatar_url=authenticated_user.avatar_url,
            email=authenticated_user.email,
        )

    with TestClient(app) as client:
        created = client.post(
            "/v1/user/repos",
            headers=auth_headers,
            json={
                "repo_url": "https://github.com/OpenAI/openai-python.git",
                "ref": "main",
            },
        )
        assert created.status_code == 200
        assert created.json()["repo_id"] == "openai/openai-python"

        removed = client.delete(
            "/v1/user/repos/openai/openai-python",
            headers=auth_headers,
        )
        assert removed.status_code == 200
        assert removed.json() == {"repo_id": "openai/openai-python", "deleted": True}

        restored = client.post(
            "/v1/user/repos",
            headers=auth_headers,
            json={
                "repo_url": "OpenAI/openai-python",
                "ref": "develop",
            },
        )
        assert restored.status_code == 200
        assert restored.json()["repo_id"] == "openai/openai-python"
        assert restored.json()["ref"] == "develop"

    with app.database.connection_context():
        repos = list(UserRepo.select())
        assert len(repos) == 1
        repo = repos[0]
        assert repo.repo_id == "openai/openai-python"
        assert repo.ref == "develop"
        assert repo.deleted_at is None


def test_get_code_context_mcp_tool_uses_injected_auth(
    app_factory,
    install_fake_auth,
) -> None:
    """Verify the MCP wrapper injects auth before invoking the search tool."""
    app = install_fake_auth(app_factory())
    handler = MCPToolHandler(app)
    tool = handler._make_tool_fn(
        collect_toolcalls(*app.engine.registries())["get_code_context"]
    )
    ctx = SimpleNamespace(
        request_context=SimpleNamespace(
            request=SimpleNamespace(headers={"Authorization": "Bearer test-token"})
        )
    )

    result = asyncio.run(
        tool(
            ctx,
            repository_name="openai/openai-python",
            task_description="Need context for a parser bug fix",
            branch="main",
            latest_commit="abc123",
            file_path="src/parser.py",
            start_line=10,
            end_line=20,
        )
    )

    assert result["status"] == "not_implemented"
    assert result["requested_by_user_id"] == "user-1"
    assert result["highlight"]["file_path"] == "src/parser.py"


def test_mcp_tool_requires_bearer_auth(app_factory) -> None:
    """Reject unauthenticated MCP calls before the handler method is invoked."""
    app = app_factory()
    handler = MCPToolHandler(app)
    tool = handler._make_tool_fn(
        collect_toolcalls(*app.engine.registries())["get_code_context"]
    )
    ctx = SimpleNamespace(
        request_context=SimpleNamespace(request=SimpleNamespace(headers={}))
    )

    with pytest.raises(PermissionError, match="Missing Authorization header"):
        asyncio.run(
            tool(
                ctx,
                repository_name="openai/openai-python",
                task_description="Need context for a parser bug fix",
            )
        )
