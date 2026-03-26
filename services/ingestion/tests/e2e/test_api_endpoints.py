from __future__ import annotations

import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

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
    )


@pytest.fixture
async def client(test_settings, db_manager):
    """Create a test client with a fake lifespan that skips Temporal."""

    @asynccontextmanager
    async def test_lifespan(app):
        app.state.settings = test_settings
        app.state.temporal_client = AsyncMock()
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = test_lifespan

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.router.lifespan_context = original_lifespan


@pytest.mark.e2e
class TestIngestionEndpoints:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_index_repos(self, client):
        resp = await client.post(
            "/index",
            json={
                "repositories": [
                    {
                        "github_repo_id": 12345,
                        "repo_url": "https://github.com/owner/repo",
                        "full_name": "owner/repo",
                        "branches": ["main"],
                    }
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert len(data["workflow_ids"]) == 1

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
            IndexedBranch.create(
                repository=repo, branch_name="main", status="indexed"
            )

        resp = await client.get("/status/11111")
        assert resp.status_code == 200
        data = resp.json()
        assert data["github_repo_id"] == 11111
        assert len(data["branches"]) == 1
        assert data["branches"][0]["status"] == "indexed"

    @pytest.mark.asyncio
    async def test_webhook_valid_push(self, client, test_settings):
        payload = {
            "ref": "refs/heads/main",
            "before": "aaa",
            "after": "bbb",
            "repository": {"id": 123, "full_name": "owner/repo"},
        }
        body = json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(
            test_settings.github_webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()

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
        sig = "sha256=" + hmac.new(
            test_settings.github_webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()

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
