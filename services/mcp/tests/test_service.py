from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.models import Repository, User, UserHiddenRepository
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
    """Add, hide, and re-add a repository without duplicating the global record."""
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
            },
        )
        assert created.status_code == 200
        assert created.json()["repo_id"] == "openai/openai-python"

        listed = client.get("/v1/user/repos", headers=auth_headers)
        assert listed.status_code == 200
        assert listed.json() == [
            {
                "id": created.json()["id"],
                "repo_id": "openai/openai-python",
                "repo_url": "https://github.com/openai/openai-python",
                "display_name": "openai/openai-python",
                "added_at": created.json()["added_at"],
                "index_status": None,
            }
        ]

        removed = client.delete(
            "/v1/user/repos/openai/openai-python",
            headers=auth_headers,
        )
        assert removed.status_code == 200
        assert removed.json() == {"repo_id": "openai/openai-python", "hidden": True}

        listed_after_delete = client.get("/v1/user/repos", headers=auth_headers)
        assert listed_after_delete.status_code == 200
        assert listed_after_delete.json() == []

        restored = client.post(
            "/v1/user/repos",
            headers=auth_headers,
            json={
                "repo_url": "OpenAI/openai-python",
            },
        )
        assert restored.status_code == 200
        assert restored.json()["id"] == created.json()["id"]
        assert restored.json()["repo_id"] == "openai/openai-python"

        listed_after_restore = client.get("/v1/user/repos", headers=auth_headers)
        assert listed_after_restore.status_code == 200
        assert len(listed_after_restore.json()) == 1
        assert listed_after_restore.json()[0]["repo_id"] == "openai/openai-python"

    with app.database.connection_context():
        repos = list(Repository.select())
        assert len(repos) == 1
        repo = repos[0]
        assert repo.repo_id == "openai/openai-python"
        hidden_repos = list(UserHiddenRepository.select())
        assert hidden_repos == []


def test_hiding_a_public_repo_only_hides_it_for_the_requesting_user(
    app_factory,
    install_fake_auth,
    auth_headers,
    authenticated_user,
) -> None:
    """Hide operations should affect only the requesting user, not the global repository."""
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
        User.create(
            id="user-2",
            github_id=456,
            github_login="second-octocat",
            display_name="Second Octocat",
            avatar_url=None,
            email="second@example.com",
        )

    with TestClient(app) as client:
        created = client.post(
            "/v1/user/repos",
            headers=auth_headers,
            json={"repo_url": "https://github.com/OpenAI/openai-python"},
        )
        assert created.status_code == 200

        removed = client.delete(
            "/v1/user/repos/openai/openai-python",
            headers=auth_headers,
        )
        assert removed.status_code == 200
        assert removed.json() == {"repo_id": "openai/openai-python", "hidden": True}

    hidden_for_user_one = app.engine.user._list_user_repos_sync(authenticated_user.id, set())
    visible_for_user_two = app.engine.user._list_user_repos_sync("user-2", set())

    assert hidden_for_user_one == []
    assert [repo.repo_id for repo in visible_for_user_two] == ["openai/openai-python"]

    with app.database.connection_context():
        assert Repository.select().count() == 1
        hidden = list(UserHiddenRepository.select())
        assert len(hidden) == 1
        assert hidden[0].user_id == authenticated_user.id


def test_list_user_repos_filters_private_visibility(
    app_factory,
    install_fake_auth,
    auth_headers,
) -> None:
    """List all public repositories and only the private repositories the user can access."""
    app = install_fake_auth(app_factory(with_db=True))

    async def visible_private_repo_ids(user_id: str) -> set[str]:
        return {"acme/private-visible"}

    app.authenticator.list_visible_private_repository_ids = visible_private_repo_ids

    with app.database.connection_context():
        Repository.create(
            github_repo_id=1001,
            repo_id="openai/openai-python",
            repo_url="https://github.com/openai/openai-python",
            display_name="openai/openai-python",
            owner_login="openai",
            owner_type="Organization",
            is_private=False,
        )
        Repository.create(
            github_repo_id=1002,
            repo_id="acme/private-visible",
            repo_url="https://github.com/acme/private-visible",
            display_name="acme/private-visible",
            owner_login="acme",
            owner_type="Organization",
            is_private=True,
        )
        Repository.create(
            github_repo_id=1003,
            repo_id="acme/private-hidden",
            repo_url="https://github.com/acme/private-hidden",
            display_name="acme/private-hidden",
            owner_login="acme",
            owner_type="Organization",
            is_private=True,
        )

    with TestClient(app) as client:
        response = client.get("/v1/user/repos", headers=auth_headers)

    assert response.status_code == 200
    assert [repo["repo_id"] for repo in response.json()] == [
        "acme/private-visible",
        "openai/openai-python",
    ]


def test_mcp_token_http_lifecycle(
    app_factory,
    install_fake_auth,
    auth_headers,
    authenticated_user,
) -> None:
    """Generate, read, authenticate with, and revoke a dedicated MCP token."""
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
        initial = client.get("/v1/auth/mcp-token", headers=auth_headers)
        assert initial.status_code == 200
        assert initial.json() == {
            "token": None,
            "issued_at": None,
            "has_token": False,
        }

        generated = client.post("/v1/auth/mcp-token", headers=auth_headers)
        assert generated.status_code == 200
        generated_token = generated.json()["token"]
        assert isinstance(generated_token, str)
        assert generated.json()["has_token"] is True
        assert generated.json()["issued_at"] is not None

        fetched = client.get("/v1/auth/mcp-token", headers=auth_headers)
        assert fetched.status_code == 200
        assert fetched.json()["token"] == generated_token
        assert fetched.json()["has_token"] is True

        resolved_auth = asyncio.run(app.authenticator.authenticate_bearer_token(generated_token))
        assert resolved_auth.id == authenticated_user.id
        assert resolved_auth.authenticated_via == "mcp"

        revoked = client.delete("/v1/auth/mcp-token", headers=auth_headers)
        assert revoked.status_code == 204

        fetched_after_revoke = client.get("/v1/auth/mcp-token", headers=auth_headers)
        assert fetched_after_revoke.status_code == 200
        assert fetched_after_revoke.json() == {
            "token": None,
            "issued_at": None,
            "has_token": False,
        }


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
