from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport

from ingestion.main import app
from ingestion.utilities.config import IngestionSettings


@pytest.fixture
def test_settings(pg_dsn):
    return IngestionSettings(
        postgres_dsn=pg_dsn,
        milvus_uri="http://localhost:19530",
        openai_api_key="test-key",
        github_webhook_secret="test-secret",
        temporal_address="localhost:7233",
        embedding_strategy="bedrock",
    )


@pytest.fixture
async def client(test_settings, db_manager):
    """Create a test client that skips Temporal by setting state directly.

    httpx's ASGITransport does not invoke ASGI lifespan events, so we
    configure app.state manually instead of replacing the lifespan.
    """
    app.state.settings = test_settings
    app.state.temporal_client = AsyncMock()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.e2e
class TestIngestionEndpoints:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_index_repos_starts_one_workflow_per_branch(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(
            "ingestion.main._ensure_repository_record",
            lambda **_: "repo-12345",
        )

        resp = await client.post(
            "/index",
            json={
                "repositories": [
                    {
                        "github_repo_id": 12345,
                        "repo_url": "https://github.com/owner/repo",
                        "full_name": "owner/repo",
                        "branches": ["main", "feature-x"],
                    }
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["workflow_ids"] == [
            "index-branch-12345-owner-repo-main",
            "index-branch-12345-owner-repo-feature-x",
        ]

        start_calls = (
            client._transport.app.state.temporal_client.start_workflow.await_args_list
        )
        assert len(start_calls) == 2
        assert start_calls[0].kwargs["id"] == "index-branch-12345-owner-repo-main"
        assert start_calls[1].kwargs["id"] == "index-branch-12345-owner-repo-feature-x"
        assert start_calls[0].args[1].embedding_strategy == "bedrock"
        assert start_calls[1].args[1].embedding_strategy == "bedrock"

    @pytest.mark.asyncio
    async def test_index_repos_skips_duplicate_branch_workflow(
        self, client, monkeypatch
    ):
        class FakeWorkflowAlreadyStartedError(Exception):
            pass

        async def fake_start_workflow(*args, **kwargs):
            if kwargs["id"] == "index-branch-12345-owner-repo-main":
                raise FakeWorkflowAlreadyStartedError("already running")
            return SimpleNamespace(id=kwargs["id"])

        monkeypatch.setattr(
            "ingestion.main._ensure_repository_record",
            lambda **_: "repo-12345",
        )
        monkeypatch.setattr(
            "ingestion.main.WorkflowAlreadyStartedError",
            FakeWorkflowAlreadyStartedError,
        )
        client._transport.app.state.temporal_client.start_workflow = AsyncMock(
            side_effect=fake_start_workflow
        )

        resp = await client.post(
            "/index",
            json={
                "repositories": [
                    {
                        "github_repo_id": 12345,
                        "repo_url": "https://github.com/owner/repo",
                        "full_name": "owner/repo",
                        "branches": ["main", "feature-x"],
                    }
                ]
            },
        )

        assert resp.status_code == 200
        assert resp.json()["workflow_ids"] == ["index-branch-12345-owner-repo-feature-x"]

    @pytest.mark.asyncio
    async def test_status_not_found(self, client):
        resp = await client.get("/status/99999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_status_found(self, client, db_manager):
        from db import IndexedBranch

        from testing_utils.factories import create_repository

        repo = create_repository(db_manager, github_repo_id=11111)
        with db_manager.connection_context():
            IndexedBranch.create(repository=repo, branch_name="main", status="indexed")

        resp = await client.get("/status/11111")
        assert resp.status_code == 200
        data = resp.json()
        assert data["github_repo_id"] == 11111
        assert len(data["branches"]) == 1
        assert data["branches"][0]["status"] == "indexed"

    @pytest.mark.asyncio
    async def test_generate_wiki_starts_workflow_with_bedrock_defaults(
        self, client, db_manager
    ):
        from testing_utils.factories import create_repository

        create_repository(
            db_manager,
            github_repo_id=22222,
            full_name="owner/repo",
        )

        resp = await client.post(
            "/generate-wiki",
            json={"github_repo_id": 22222, "branch": "main"},
        )

        assert resp.status_code == 200
        assert resp.json()["workflow_id"] == "wiki-22222-main"
        start_call = (
            client._transport.app.state.temporal_client.start_workflow.await_args
        )
        assert start_call.args[1].llm_strategy == "bedrock"
        assert start_call.args[1].embedding_strategy == "bedrock"

    @pytest.mark.asyncio
    async def test_generate_wiki_rejects_missing_openai_api_key(
        self, client, db_manager
    ):
        from testing_utils.factories import create_repository

        create_repository(
            db_manager,
            github_repo_id=33333,
            full_name="owner/repo",
        )
        client._transport.app.state.settings = IngestionSettings(
            postgres_dsn=client._transport.app.state.settings.postgres_dsn,
            milvus_uri="http://localhost:19530",
            openai_api_key="",
            github_webhook_secret="test-secret",
            temporal_address="localhost:7233",
            embedding_strategy="bedrock",
            llm_strategy="openai",
        )

        resp = await client.post(
            "/generate-wiki",
            json={"github_repo_id": 33333, "branch": "main"},
        )

        assert resp.status_code == 400
        assert "OPENAI_API_KEY" in resp.json()["detail"]
        client._transport.app.state.temporal_client.start_workflow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_webhook_valid_push(self, client, test_settings):
        payload = {
            "ref": "refs/heads/main",
            "before": "aaa",
            "after": "bbb",
            "repository": {"id": 123, "full_name": "owner/repo"},
        }
        body = json.dumps(payload).encode()
        sig = (
            "sha256="
            + hmac.new(
                test_settings.github_webhook_secret.encode(), body, hashlib.sha256
            ).hexdigest()
        )

        resp = await client.post(
            "/webhook",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "push",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
        assert resp.json()["workflow_id"] == "incremental-123-main"
        start_call = (
            client._transport.app.state.temporal_client.start_workflow.await_args
        )
        assert start_call.kwargs["id"] == "incremental-123-main"
        assert start_call.args[1].embedding_strategy == "bedrock"

    @pytest.mark.asyncio
    async def test_webhook_duplicate_push_signals_existing_workflow(
        self, client, test_settings, monkeypatch
    ):
        class FakeWorkflowAlreadyStartedError(Exception):
            pass

        handle = SimpleNamespace(signal=AsyncMock())
        payload = {
            "ref": "refs/heads/main",
            "before": "aaa",
            "after": "bbb",
            "repository": {"id": 123, "full_name": "owner/repo"},
        }
        body = json.dumps(payload).encode()
        sig = (
            "sha256="
            + hmac.new(
                test_settings.github_webhook_secret.encode(), body, hashlib.sha256
            ).hexdigest()
        )

        monkeypatch.setattr(
            "ingestion.main.WorkflowAlreadyStartedError",
            FakeWorkflowAlreadyStartedError,
        )
        client._transport.app.state.temporal_client.start_workflow = AsyncMock(
            side_effect=FakeWorkflowAlreadyStartedError("already running")
        )
        client._transport.app.state.temporal_client.get_workflow_handle = MagicMock(
            return_value=handle
        )

        resp = await client.post(
            "/webhook",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "push",
                "Content-Type": "application/json",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["workflow_id"] == "incremental-123-main"
        client._transport.app.state.temporal_client.get_workflow_handle.assert_called_once_with(
            "incremental-123-main"
        )
        handle.signal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_webhook_invalid_signature(self, client):
        payload = {
            "ref": "refs/heads/main",
            "before": "a",
            "after": "b",
            "repository": {"id": 1, "full_name": "o/r"},
        }
        resp = await client.post(
            "/webhook",
            content=json.dumps(payload).encode(),
            headers={
                "X-Hub-Signature-256": "sha256=wrong",
                "X-GitHub-Event": "push",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_webhook_non_push_ignored(self, client, test_settings):
        payload = {}
        body = json.dumps(payload).encode()
        sig = (
            "sha256="
            + hmac.new(
                test_settings.github_webhook_secret.encode(), body, hashlib.sha256
            ).hexdigest()
        )

        resp = await client.post(
            "/webhook",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "ping",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
