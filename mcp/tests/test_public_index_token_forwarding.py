"""Tests for request-scoped token forwarding on public index-control routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.server import app
from src.types import IndexStatus, StartIndexJobResponse


def _start_payload() -> dict[str, object]:
    """Build a valid start-index payload for public index-control routes."""
    return {
        "repo_id": "octo-org/octo-repo",
        "repo_url": "https://github.com/octo-org/octo-repo",
        "ref": "main",
        "trigger": "manual",
        "requested_by": "api_test",
        "force_reindex": False,
    }


def test_start_job_forwards_header_token_to_service_request() -> None:
    """`POST /v1/index/jobs` should forward request bearer token when present."""
    with (
        TestClient(app) as client,
        patch(
            "src.routes.public.index_control.index_control_service.start_job",
            new=AsyncMock(
                return_value=StartIndexJobResponse(
                    job_id="job_001",
                    workflow_id="runtime-index:octo-org/octo-repo:main",
                    status=IndexStatus.PENDING,
                )
            ),
        ) as mock_start_job,
    ):
        response = client.post(
            "/v1/index/jobs",
            json=_start_payload(),
            headers={"Authorization": "Bearer ghs_public_route"},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"
    mock_start_job.assert_awaited_once()
    request_model = mock_start_job.await_args.args[0]
    assert request_model.github_token == "ghs_public_route"


def test_start_job_without_header_keeps_github_token_none() -> None:
    """`POST /v1/index/jobs` should not require token for public-repo flows."""
    with (
        TestClient(app) as client,
        patch(
            "src.routes.public.index_control.index_control_service.start_job",
            new=AsyncMock(
                return_value=StartIndexJobResponse(
                    job_id="job_002",
                    workflow_id="runtime-index:octo-org/octo-repo:main",
                    status=IndexStatus.PENDING,
                )
            ),
        ) as mock_start_job,
    ):
        response = client.post("/v1/index/jobs", json=_start_payload())

    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"
    mock_start_job.assert_awaited_once()
    request_model = mock_start_job.await_args.args[0]
    assert request_model.github_token is None


def test_retry_forwards_token_to_retry_request() -> None:
    """Retry endpoint should forward request-scoped token into retry request model."""
    with (
        TestClient(app) as client,
        patch(
            "src.routes.public.index_control.index_control_service.retry_job",
            new=AsyncMock(
                return_value=StartIndexJobResponse(
                    job_id="job_retry_001",
                    workflow_id="runtime-index:octo-org/octo-repo:main:force:123",
                    status=IndexStatus.PENDING,
                )
            ),
        ) as mock_retry_job,
    ):
        response = client.post(
            "/v1/index/repos/octo-org/octo-repo/retry?ref=main",
            json={},
            headers={"X-GitHub-Token": "ghs_retry_header"},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"
    mock_retry_job.assert_awaited_once()
    retry_request = mock_retry_job.await_args.kwargs["request"]
    assert retry_request.github_token == "ghs_retry_header"
