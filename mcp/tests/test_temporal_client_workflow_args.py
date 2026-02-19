"""Unit tests for Temporal client workflow argument construction."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.clients.temporal import TemporalClientWrapper


def test_start_runtime_index_workflow_includes_github_token_when_provided() -> None:
    """Temporal start args should include `github_token` when supplied."""
    wrapper = TemporalClientWrapper()
    mock_client = AsyncMock()
    mock_client.start_workflow = AsyncMock(
        return_value=SimpleNamespace(first_execution_run_id="run_001")
    )

    async def _run() -> None:
        with patch.object(wrapper, "_get_client", new=AsyncMock(return_value=mock_client)):
            await wrapper.start_runtime_index_workflow(
                repo_id="octo/repo",
                repo_url="https://github.com/octo/repo",
                ref="main",
                workflow_id="runtime-index:octo/repo:main",
                force_reindex=False,
                github_token="ghs_temporal_token",
            )

    asyncio.run(_run())

    mock_client.start_workflow.assert_awaited_once()
    workflow_args = mock_client.start_workflow.await_args.args[1]
    assert workflow_args["github_token"] == "ghs_temporal_token"


def test_start_runtime_index_workflow_omits_github_token_when_not_provided() -> None:
    """Temporal start args should omit `github_token` when absent."""
    wrapper = TemporalClientWrapper()
    mock_client = AsyncMock()
    mock_client.start_workflow = AsyncMock(
        return_value=SimpleNamespace(first_execution_run_id="run_002")
    )

    async def _run() -> None:
        with patch.object(wrapper, "_get_client", new=AsyncMock(return_value=mock_client)):
            await wrapper.start_runtime_index_workflow(
                repo_id="octo/repo",
                repo_url="https://github.com/octo/repo",
                ref="main",
                workflow_id="runtime-index:octo/repo:main",
                force_reindex=False,
                github_token=None,
            )

    asyncio.run(_run())

    mock_client.start_workflow.assert_awaited_once()
    workflow_args = mock_client.start_workflow.await_args.args[1]
    assert "github_token" not in workflow_args
