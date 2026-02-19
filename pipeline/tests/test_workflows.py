"""Unit tests for pipeline workflow orchestration behavior."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src import workflows


def _run(coro):
    """Execute one async coroutine inside a fresh event loop."""
    return asyncio.run(coro)


def _runtime_params() -> workflows.RuntimeIndexParams:
    """Build standard runtime workflow input parameters for tests."""
    return workflows.RuntimeIndexParams(
        repo_id="octo/repo",
        repo_url="https://github.com/octo/repo",
        ref="main",
        force_reindex=False,
    )


def test_runtime_workflow_happy_path() -> None:
    """Runtime workflow should complete and return READY metadata."""
    captured_success_payloads: list[dict[str, object]] = []

    async def execute_side_effect(activity_fn, payload, **kwargs):
        if activity_fn is workflows.persist_runtime_index_start_activity:
            return {"ok": True}
        if activity_fn is workflows.persist_runtime_index_progress_activity:
            return {"ok": True}
        if activity_fn is workflows.ingest_activity:
            return {
                **payload,
                "artifact_dir": "/tmp/artifacts",
                "ingest_path": "/tmp/ingest.jsonl",
                "snapshot_sha": "abc123",
                "ingest_stats": {"file_count": 1, "total_text_bytes": 10},
            }
        if activity_fn is workflows.clean_activity:
            return {
                **payload,
                "clean_path": "/tmp/clean.jsonl",
                "clean_stats": {"document_count": 1, "dropped_records": 0},
            }
        if activity_fn is workflows.transform_activity:
            return {
                **payload,
                "transform_path": "/tmp/transform.jsonl",
                "transform_stats": {
                    "chunk_count": 1,
                    "chunk_chars_total": 10,
                    "corpus_hash": "hash1",
                },
            }
        if activity_fn is workflows.store_activity:
            return {**payload, "snapshot_sha": "abc123"}
        if activity_fn is workflows.persist_runtime_index_success_activity:
            captured_success_payloads.append(payload)
            return {"ok": True}
        raise AssertionError(f"Unexpected activity dispatch: {activity_fn}")

    mock_execute = AsyncMock(side_effect=execute_side_effect)
    with (
        patch.object(
            workflows.workflow,
            "info",
            return_value=SimpleNamespace(
                workflow_id="runtime-index:octo/repo:main",
                run_id="run_001",
            ),
        ),
        patch.object(workflows.workflow, "execute_activity", new=mock_execute),
        patch.object(workflows, "_log_workflow_info"),
        patch.object(workflows, "_log_workflow_warning"),
        patch.object(workflows, "_log_workflow_error"),
    ):
        result = _run(workflows.RuntimeIndexWorkflow().run(_runtime_params()))

    assert result["status"] == "READY"
    assert result["workflow_id"] == "runtime-index:octo/repo:main"
    assert result["job_id"] == "run_001"
    assert len(captured_success_payloads) == 1
    assert captured_success_payloads[0]["snapshot_sha"] == "abc123"


def test_runtime_workflow_failure_path_persists_classified_error() -> None:
    """Runtime workflow should persist classified error metadata on failure."""
    captured_failure_payloads: list[dict[str, object]] = []

    async def execute_side_effect(activity_fn, payload, **kwargs):
        if activity_fn is workflows.persist_runtime_index_start_activity:
            return {"ok": True}
        if activity_fn is workflows.persist_runtime_index_progress_activity:
            return {"ok": True}
        if activity_fn is workflows.ingest_activity:
            return {
                **payload,
                "artifact_dir": "/tmp/artifacts",
                "ingest_path": "/tmp/ingest.jsonl",
                "snapshot_sha": "abc123",
            }
        if activity_fn is workflows.clean_activity:
            raise ValueError("invalid cleaned payload")
        if activity_fn is workflows.persist_runtime_index_failure_activity:
            captured_failure_payloads.append(payload)
            return {"ok": True}
        raise AssertionError(f"Unexpected activity dispatch: {activity_fn}")

    mock_execute = AsyncMock(side_effect=execute_side_effect)
    with (
        patch.object(
            workflows.workflow,
            "info",
            return_value=SimpleNamespace(
                workflow_id="runtime-index:octo/repo:main",
                run_id="run_002",
            ),
        ),
        patch.object(workflows.workflow, "execute_activity", new=mock_execute),
        patch.object(workflows, "_log_workflow_info"),
        patch.object(workflows, "_log_workflow_warning"),
        patch.object(workflows, "_log_workflow_error"),
        pytest.raises(ValueError, match="invalid cleaned payload"),
    ):
        _run(workflows.RuntimeIndexWorkflow().run(_runtime_params()))

    assert len(captured_failure_payloads) == 1
    failure_payload = captured_failure_payloads[0]
    assert failure_payload["error_code"] == "RUNTIME_INDEX_TERMINAL_VALIDATION"
    assert "[terminal]" in failure_payload["error_message"]
    assert failure_payload["stage"] == "CLEAN"


def test_offline_workflow_happy_path() -> None:
    """Offline workflow should execute all stages and return READY."""
    mock_execute = AsyncMock(return_value={"ok": True})
    with (
        patch.object(
            workflows.workflow,
            "info",
            return_value=SimpleNamespace(
                workflow_id="offline-datasets:benchmark:v1",
                run_id="run_offline_001",
            ),
        ),
        patch.object(workflows.workflow, "execute_activity", new=mock_execute),
        patch.object(workflows, "_log_workflow_info"),
        patch.object(workflows, "_log_workflow_warning"),
        patch.object(workflows, "_log_workflow_error"),
    ):
        result = _run(
            workflows.OfflineDatasetWorkflow().run(
                workflows.OfflineDatasetParams(
                    dataset_name="swebench",
                    dataset_version="v1",
                    dataset_source_path="/tmp/swebench-v1.jsonl",
                )
            )
        )

    assert result["status"] == "READY"
    assert mock_execute.await_count == 4


def test_offline_workflow_failure_path() -> None:
    """Offline workflow should propagate stage failures."""

    async def execute_side_effect(activity_fn, payload, **kwargs):
        if activity_fn is workflows.transform_activity:
            raise RuntimeError("offline transform failed")
        return {"ok": True}

    mock_execute = AsyncMock(side_effect=execute_side_effect)
    with (
        patch.object(
            workflows.workflow,
            "info",
            return_value=SimpleNamespace(
                workflow_id="offline-datasets:benchmark:v1",
                run_id="run_offline_002",
            ),
        ),
        patch.object(workflows.workflow, "execute_activity", new=mock_execute),
        patch.object(workflows, "_log_workflow_info"),
        patch.object(workflows, "_log_workflow_warning"),
        patch.object(workflows, "_log_workflow_error"),
        pytest.raises(RuntimeError, match="offline transform failed"),
    ):
        _run(
            workflows.OfflineDatasetWorkflow().run(
                workflows.OfflineDatasetParams(
                    dataset_name="swebench",
                    dataset_version="v1",
                    dataset_source_path="/tmp/swebench-v1.jsonl",
                )
            )
        )


def test_mental_model_workflow_happy_path() -> None:
    """Mental-model workflow should return READY on successful activity."""
    mock_execute = AsyncMock(return_value={"ok": True})
    with (
        patch.object(
            workflows.workflow,
            "info",
            return_value=SimpleNamespace(
                workflow_id="mental-model:octo/repo",
                run_id="run_mm_001",
            ),
        ),
        patch.object(workflows.workflow, "execute_activity", new=mock_execute),
        patch.object(workflows, "_log_workflow_info"),
        patch.object(workflows, "_log_workflow_warning"),
        patch.object(workflows, "_log_workflow_error"),
    ):
        result = _run(
            workflows.MentalModelWorkflow().run(
                workflows.MentalModelParams(
                    repo_id="octo/repo",
                    from_sha="abc",
                    to_sha="def",
                )
            )
        )

    assert result["status"] == "READY"
    assert mock_execute.await_count == 1


def test_mental_model_workflow_failure_path() -> None:
    """Mental-model workflow should surface underlying stage failures."""
    mock_execute = AsyncMock(side_effect=RuntimeError("mental model failed"))
    with (
        patch.object(
            workflows.workflow,
            "info",
            return_value=SimpleNamespace(
                workflow_id="mental-model:octo/repo",
                run_id="run_mm_002",
            ),
        ),
        patch.object(workflows.workflow, "execute_activity", new=mock_execute),
        patch.object(workflows, "_log_workflow_info"),
        patch.object(workflows, "_log_workflow_warning"),
        patch.object(workflows, "_log_workflow_error"),
        pytest.raises(RuntimeError, match="mental model failed"),
    ):
        _run(
            workflows.MentalModelWorkflow().run(
                workflows.MentalModelParams(
                    repo_id="octo/repo",
                    from_sha=None,
                    to_sha=None,
                )
            )
        )
