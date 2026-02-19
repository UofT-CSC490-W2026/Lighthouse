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
    captured_metrics_payloads: list[dict[str, object]] = []

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
        if activity_fn is workflows.persist_pipeline_run_metrics_activity:
            captured_metrics_payloads.append(payload)
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
    assert len(captured_metrics_payloads) == 1
    assert captured_metrics_payloads[0]["workflow_type"] == "RuntimeIndexWorkflow"
    assert captured_metrics_payloads[0]["status"] == "READY"
    assert captured_metrics_payloads[0]["records_in"] == 1
    assert captured_metrics_payloads[0]["records_out"] == 1


def test_runtime_workflow_failure_path_persists_classified_error() -> None:
    """Runtime workflow should persist classified error metadata on failure."""
    captured_failure_payloads: list[dict[str, object]] = []
    captured_metrics_payloads: list[dict[str, object]] = []

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
        if activity_fn is workflows.persist_pipeline_run_metrics_activity:
            captured_metrics_payloads.append(payload)
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
    assert len(captured_metrics_payloads) == 1
    assert captured_metrics_payloads[0]["workflow_type"] == "RuntimeIndexWorkflow"
    assert captured_metrics_payloads[0]["status"] == "FAILED"
    assert captured_metrics_payloads[0]["failure_count"] == 1


def test_runtime_workflow_propagates_optional_github_token() -> None:
    """Runtime workflow should forward optional GitHub token to ingest payload."""
    captured_ingest_payloads: list[dict[str, object]] = []

    async def execute_side_effect(activity_fn, payload, **kwargs):
        if activity_fn is workflows.persist_runtime_index_start_activity:
            return {"ok": True}
        if activity_fn is workflows.persist_runtime_index_progress_activity:
            return {"ok": True}
        if activity_fn is workflows.ingest_activity:
            captured_ingest_payloads.append(dict(payload))
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
                    "corpus_hash": "hash2",
                },
            }
        if activity_fn is workflows.store_activity:
            return {**payload, "snapshot_sha": "abc123"}
        if activity_fn is workflows.persist_runtime_index_success_activity:
            return {"ok": True}
        if activity_fn is workflows.persist_pipeline_run_metrics_activity:
            return {"ok": True}
        raise AssertionError(f"Unexpected activity dispatch: {activity_fn}")

    mock_execute = AsyncMock(side_effect=execute_side_effect)
    with (
        patch.object(
            workflows.workflow,
            "info",
            return_value=SimpleNamespace(
                workflow_id="runtime-index:octo/repo:main",
                run_id="run_token_001",
            ),
        ),
        patch.object(workflows.workflow, "execute_activity", new=mock_execute),
        patch.object(workflows, "_log_workflow_info"),
        patch.object(workflows, "_log_workflow_warning"),
        patch.object(workflows, "_log_workflow_error"),
    ):
        result = _run(
            workflows.RuntimeIndexWorkflow().run(
                workflows.RuntimeIndexParams(
                    repo_id="octo/repo",
                    repo_url="https://github.com/octo/repo",
                    ref="main",
                    github_token="ghs_runtime_token",
                    force_reindex=False,
                )
            )
        )

    assert result["status"] == "READY"
    assert len(captured_ingest_payloads) == 1
    assert captured_ingest_payloads[0]["github_token"] == "ghs_runtime_token"


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
    assert mock_execute.await_count == 5


def test_offline_workflow_propagates_incremental_controls() -> None:
    """Offline workflow should pass rolling-window controls to stage payloads."""
    captured_ingest_payload: dict[str, object] = {}

    async def execute_side_effect(activity_fn, payload, **kwargs):
        if activity_fn is workflows.ingest_activity:
            captured_ingest_payload.update(payload)
        return {**payload, "ok": True}

    mock_execute = AsyncMock(side_effect=execute_side_effect)
    with (
        patch.object(
            workflows.workflow,
            "info",
            return_value=SimpleNamespace(
                workflow_id="offline-datasets:issue_pr_diff:rolling-live",
                run_id="run_offline_rolling_001",
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
                    dataset_name="issue_pr_diff",
                    dataset_version="rolling-live",
                    dataset_source_path="/tmp/issue-pr-diff.jsonl",
                    watermark_start="2026-02-01T00:00:00Z",
                    watermark_end="2026-02-02T00:00:00Z",
                    max_records=500,
                    source_cursor="cursor-001",
                )
            )
        )

    assert result["status"] == "READY"
    assert captured_ingest_payload["dataset_name"] == "issue_pr_diff"
    assert captured_ingest_payload["dataset_version"] == "rolling-live"
    assert captured_ingest_payload["watermark_start"] == "2026-02-01T00:00:00Z"
    assert captured_ingest_payload["watermark_end"] == "2026-02-02T00:00:00Z"
    assert captured_ingest_payload["max_records"] == 500
    assert captured_ingest_payload["source_cursor"] == "cursor-001"


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
    assert mock_execute.await_count == 2


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


def test_evaluation_refresh_workflow_happy_path() -> None:
    """Evaluation refresh workflow should execute and return READY."""
    async def execute_side_effect(activity_fn, payload, **kwargs):
        if activity_fn is workflows.evaluation_refresh_activity:
            return {**payload, "evaluation_refresh_stats": {"dataset_instance_count": 42}}
        if activity_fn is workflows.baseline_evaluation_activity:
            return {
                **payload,
                "baseline_evaluation_stats": {
                    "total_instances": 42,
                    "fail_to_pass_rate": 0.5,
                    "regression_rate": 0.1,
                },
            }
        if activity_fn is workflows.persist_pipeline_run_metrics_activity:
            return {"ok": True}
        raise AssertionError(f"Unexpected activity dispatch: {activity_fn}")

    mock_execute = AsyncMock(side_effect=execute_side_effect)
    with (
        patch.object(
            workflows.workflow,
            "info",
            return_value=SimpleNamespace(
                workflow_id="evaluation-refresh:swebench:v1:monthly",
                run_id="run_eval_001",
            ),
        ),
        patch.object(workflows.workflow, "execute_activity", new=mock_execute),
        patch.object(workflows, "_log_workflow_info"),
        patch.object(workflows, "_log_workflow_warning"),
        patch.object(workflows, "_log_workflow_error"),
    ):
        result = _run(
            workflows.EvaluationRefreshWorkflow().run(
                workflows.EvaluationRefreshParams(
                    dataset_name="swebench",
                    dataset_version="v1",
                )
            )
        )

    assert result["status"] == "READY"
    assert mock_execute.await_count == 3


def test_evaluation_refresh_workflow_failure_path() -> None:
    """Evaluation refresh workflow should surface stage failures."""
    mock_execute = AsyncMock(side_effect=RuntimeError("evaluation refresh failed"))
    with (
        patch.object(
            workflows.workflow,
            "info",
            return_value=SimpleNamespace(
                workflow_id="evaluation-refresh:swebench:v1:monthly",
                run_id="run_eval_002",
            ),
        ),
        patch.object(workflows.workflow, "execute_activity", new=mock_execute),
        patch.object(workflows, "_log_workflow_info"),
        patch.object(workflows, "_log_workflow_warning"),
        patch.object(workflows, "_log_workflow_error"),
        pytest.raises(RuntimeError, match="evaluation refresh failed"),
    ):
        _run(
            workflows.EvaluationRefreshWorkflow().run(
                workflows.EvaluationRefreshParams(
                    dataset_name="swebench",
                    dataset_version="v1",
                )
            )
        )
