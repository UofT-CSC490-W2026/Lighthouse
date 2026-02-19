"""Unit tests for monthly evaluation refresh trigger path."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from temporalio.exceptions import WorkflowAlreadyStartedError

from src.evaluation_refresh_trigger import (
    EvaluationRefreshTriggerClient,
    StartEvaluationRefreshRequest,
    evaluation_refresh_workflow_id,
)


def _run(coro):
    """Execute one async coroutine inside a fresh event loop."""
    return asyncio.run(coro)


def test_evaluation_refresh_workflow_id_is_canonical() -> None:
    """Workflow-id builder should generate deterministic monthly ids."""
    workflow_id = evaluation_refresh_workflow_id(
        dataset_name=" SWE-bench ",
        dataset_version="V1",
    )
    assert workflow_id == "evaluation-refresh:swe-bench:v1:monthly"


def test_start_monthly_evaluation_refresh_happy_path() -> None:
    """Trigger client should start monthly refresh workflow with cron schedule."""
    fake_handle = SimpleNamespace(first_execution_run_id="run_eval_123")
    fake_client = SimpleNamespace(
        start_workflow=AsyncMock(return_value=fake_handle),
    )
    request = StartEvaluationRefreshRequest(
        dataset_name="swebench",
        dataset_version="v1",
        cron_schedule="0 0 1 * *",
        trigger="monthly_schedule",
        requested_by="unit_test",
    )
    with patch(
        "src.evaluation_refresh_trigger.Client.connect",
        new=AsyncMock(return_value=fake_client),
    ):
        result = _run(EvaluationRefreshTriggerClient().start_monthly(request))

    assert result.status == "PENDING"
    assert result.run_id == "run_eval_123"
    assert result.reused_existing is False
    assert result.workflow_id == "evaluation-refresh:swebench:v1:monthly"
    assert result.cron_schedule == "0 0 1 * *"

    fake_client.start_workflow.assert_awaited_once()
    call = fake_client.start_workflow.await_args
    assert call.args[0] == "EvaluationRefreshWorkflow"
    payload = call.args[1]
    assert payload["dataset_name"] == "swebench"
    assert payload["dataset_version"] == "v1"
    assert payload["trigger"] == "monthly_schedule"
    assert payload["requested_by"] == "unit_test"
    assert call.kwargs["id"] == "evaluation-refresh:swebench:v1:monthly"
    assert call.kwargs["cron_schedule"] == "0 0 1 * *"


def test_start_monthly_evaluation_refresh_reuses_existing_schedule() -> None:
    """Trigger client should reuse existing monthly schedule on collisions."""
    fake_workflow_handle = SimpleNamespace(
        describe=AsyncMock(return_value=SimpleNamespace(run_id="existing_eval_run"))
    )
    fake_client = SimpleNamespace(
        start_workflow=AsyncMock(
            side_effect=WorkflowAlreadyStartedError(
                "evaluation-refresh:swebench:v1:monthly",
                "EvaluationRefreshWorkflow",
            )
        ),
        get_workflow_handle=Mock(return_value=fake_workflow_handle),
    )
    request = StartEvaluationRefreshRequest(
        dataset_name="swebench",
        dataset_version="v1",
    )
    with patch(
        "src.evaluation_refresh_trigger.Client.connect",
        new=AsyncMock(return_value=fake_client),
    ):
        result = _run(EvaluationRefreshTriggerClient().start_monthly(request))

    assert result.status == "PENDING"
    assert result.reused_existing is True
    assert result.workflow_id == "evaluation-refresh:swebench:v1:monthly"
    assert result.run_id == "existing_eval_run"
