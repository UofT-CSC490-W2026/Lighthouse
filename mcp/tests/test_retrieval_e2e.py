"""Route-level retrieval test for READY index state and non-empty tool output."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from runtime_retrieval import RuntimeChunkHit

from src.server import app
from src.types import IndexStatus, RepoIndexStateResponse


def _payload() -> dict[str, object]:
    """Build one valid context-tool request payload."""
    return {
        "repo_id": "octo-org/octo-repo",
        "ref": "main",
        "file": "src/parser.py",
        "function": "parse_config",
        "task_description": "Fix parser edge-case for empty list input",
        "top_k": 5,
    }


def _ready_state() -> RepoIndexStateResponse:
    """Return READY repo state fixture to simulate successful runtime indexing."""
    return RepoIndexStateResponse(
        repo_id="octo-org/octo-repo",
        ref="main",
        status=IndexStatus.READY,
        snapshot_sha="abc123def",
        active_job_id=None,
    )


def test_ready_index_returns_non_empty_context_result() -> None:
    """READY + retrieval hit should return a non-empty context tool result."""
    retrieval_hits = [
        RuntimeChunkHit(
            chunk_id="chunk_001",
            repo_id="octo-org/octo-repo",
            ref="main",
            snapshot_sha="abc123def",
            path="src/parser.py",
            chunk_index=0,
            start_char=0,
            end_char=80,
            text="def parse_config(payload):\n    if payload is None:\n        return []",
            text_hash="hash_001",
            score=0.92,
        )
    ]

    with (
        TestClient(app) as client,
        patch(
            "src.routes.tool.common.index_control_service.get_repo_state",
            new=AsyncMock(return_value=_ready_state()),
        ),
        patch(
            "src.services.retrieval_backend_service.search",
            new=AsyncMock(return_value=retrieval_hits),
        ),
    ):
        response = client.post("/tools/get_context_for_change", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["index"]["status"] == "READY"
    assert body["result"] is not None
    assert len(body["result"]["items"]) == 1
    item = body["result"]["items"][0]
    assert item["location"] == "src/parser.py:0-80"
    assert item["content"]
    assert item["relevance_score"] > 0
