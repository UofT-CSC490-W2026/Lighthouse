"""Integration-style pytest coverage for MCP tool index-state gating behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.server import app
from src.types import (
    GetContextForChangeResponse,
    IndexStatus,
    RepoIndexStateResponse,
    StartIndexJobResponse,
)


def _payload() -> dict[str, object]:
    """Build a valid tool request payload with required repo context."""
    return {
        "repo_id": "octo-org/octo-repo",
        "ref": "main",
        "file": "src/service.py",
        "task_description": "add input validation to handler",
        "top_k": 5,
    }


def _repo_state(
    status: IndexStatus,
    *,
    active_job_id: str | None = None,
    snapshot_sha: str | None = None,
) -> RepoIndexStateResponse:
    """Construct canonical repo state response fixtures."""
    return RepoIndexStateResponse(
        repo_id="octo-org/octo-repo",
        ref="main",
        status=status,
        snapshot_sha=snapshot_sha,
        active_job_id=active_job_id,
    )


def test_ready_state_serves_tool_result() -> None:
    """READY should execute tool logic and return result payload."""
    with (
        TestClient(app) as client,
        patch(
            "src.routes.tool.common.index_control_service.get_repo_state",
            new=AsyncMock(
                return_value=_repo_state(IndexStatus.READY, snapshot_sha="abc123")
            ),
        ),
        patch(
            "src.routes.tool.context.context_service.get_context_for_change",
            new=AsyncMock(return_value=GetContextForChangeResponse(items=[])),
        ) as mock_context,
    ):
        response = client.post("/tools/get_context_for_change", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["index"]["status"] == "READY"
    assert body["index"]["snapshot_sha"] == "abc123"
    assert body["result"] is not None
    assert body["message"] is None
    assert body["retry"] is None
    mock_context.assert_awaited_once()


def test_stale_state_serves_result_with_stale_message() -> None:
    """STALE should still execute the tool and include staleness notice."""
    with (
        TestClient(app) as client,
        patch(
            "src.routes.tool.common.index_control_service.get_repo_state",
            new=AsyncMock(
                return_value=_repo_state(IndexStatus.STALE, snapshot_sha="oldsha")
            ),
        ),
        patch(
            "src.routes.tool.context.context_service.get_context_for_change",
            new=AsyncMock(return_value=GetContextForChangeResponse(items=[])),
        ) as mock_context,
    ):
        response = client.post("/tools/get_context_for_change", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["index"]["status"] == "STALE"
    assert body["result"] is not None
    assert "stale" in (body["message"] or "").lower()
    assert body["retry"] is None
    mock_context.assert_awaited_once()


def test_pending_state_returns_pending_envelope_without_tool_execution() -> None:
    """PENDING should short-circuit and return pending metadata only."""
    with (
        TestClient(app) as client,
        patch(
            "src.routes.tool.common.index_control_service.get_repo_state",
            new=AsyncMock(
                return_value=_repo_state(IndexStatus.PENDING, active_job_id="job_100")
            ),
        ),
        patch(
            "src.routes.tool.context.context_service.get_context_for_change",
            new=AsyncMock(return_value=GetContextForChangeResponse(items=[])),
        ) as mock_context,
    ):
        response = client.post("/tools/get_context_for_change", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["index"]["status"] == "PENDING"
    assert body["index"]["job_id"] == "job_100"
    assert body["result"] is None
    assert "progress" in (body["message"] or "").lower()
    assert body["retry"] is None
    mock_context.assert_not_awaited()


def test_failed_state_returns_retry_hint_without_tool_execution() -> None:
    """FAILED should short-circuit and include retry guidance metadata."""
    with (
        TestClient(app) as client,
        patch(
            "src.routes.tool.common.index_control_service.get_repo_state",
            new=AsyncMock(return_value=_repo_state(IndexStatus.FAILED)),
        ),
        patch(
            "src.routes.tool.context.context_service.get_context_for_change",
            new=AsyncMock(return_value=GetContextForChangeResponse(items=[])),
        ) as mock_context,
    ):
        response = client.post("/tools/get_context_for_change", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["index"]["status"] == "FAILED"
    assert body["result"] is None
    assert "failed" in (body["message"] or "").lower()
    assert body["retry"] is not None
    assert body["retry"]["method"] == "POST"
    assert "/v1/index/repos/" in body["retry"]["endpoint"]
    mock_context.assert_not_awaited()


def test_not_found_state_auto_starts_job_and_returns_pending() -> None:
    """NOT_FOUND should auto-start indexing and return pending envelope."""
    with (
        TestClient(app) as client,
        patch(
            "src.routes.tool.common.index_control_service.get_repo_state",
            new=AsyncMock(return_value=_repo_state(IndexStatus.NOT_FOUND)),
        ),
        patch(
            "src.routes.tool.common.index_control_service.start_job",
            new=AsyncMock(
                return_value=StartIndexJobResponse(
                    job_id="job_auto_001",
                    workflow_id="runtime-index:octo-org/octo-repo:main",
                    status=IndexStatus.PENDING,
                )
            ),
        ) as mock_start_job,
        patch(
            "src.routes.tool.context.context_service.get_context_for_change",
            new=AsyncMock(return_value=GetContextForChangeResponse(items=[])),
        ) as mock_context,
    ):
        response = client.post("/tools/get_context_for_change", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["index"]["status"] == "PENDING"
    assert body["index"]["job_id"] == "job_auto_001"
    assert body["result"] is None
    assert "started runtime indexing job" in (body["message"] or "").lower()
    assert body["retry"] is None
    mock_context.assert_not_awaited()
    mock_start_job.assert_awaited_once()

    start_request = mock_start_job.await_args.args[0]
    assert start_request.repo_id == "octo-org/octo-repo"
    assert start_request.ref == "main"
    assert start_request.trigger == "mcp_auto"
    assert start_request.requested_by == "get_context_for_change"
    assert start_request.force_reindex is False
