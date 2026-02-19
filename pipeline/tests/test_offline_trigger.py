"""Unit tests for offline benchmark ingestion trigger path."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from temporalio.exceptions import WorkflowAlreadyStartedError

from src.offline_trigger import (
    OfflineIngestionTriggerClient,
    StartOfflineIngestionRequest,
    offline_dataset_workflow_id,
)


def _run(coro):
    """Execute one async coroutine inside a fresh event loop."""
    return asyncio.run(coro)


def test_offline_dataset_workflow_id_is_canonical_and_sanitized() -> None:
    """Workflow-id builder should normalize tokens and preserve idempotency shape."""
    workflow_id = offline_dataset_workflow_id(
        dataset_name=" SWE-bench ",
        dataset_version="v1.0-beta",
    )
    assert workflow_id == "offline-datasets:swe-bench:v1.0-beta"


def test_start_offline_ingestion_happy_path() -> None:
    """Trigger client should start a new offline workflow with canonical args."""
    fake_handle = SimpleNamespace(first_execution_run_id="run_offline_123")
    fake_client = SimpleNamespace(
        start_workflow=AsyncMock(return_value=fake_handle),
    )
    request = StartOfflineIngestionRequest(
        dataset_name="swebench",
        dataset_version="v1",
        dataset_source_path="/tmp/swebench-v1.jsonl",
        trigger="manual",
        requested_by="unit_test",
        source_event_id=None,
        force_reingest=False,
    )
    with patch("src.offline_trigger.Client.connect", new=AsyncMock(return_value=fake_client)):
        result = _run(OfflineIngestionTriggerClient().start(request))

    assert result.status == "PENDING"
    assert result.run_id == "run_offline_123"
    assert result.reused_existing is False
    assert result.workflow_id == "offline-datasets:swebench:v1"

    fake_client.start_workflow.assert_awaited_once()
    call = fake_client.start_workflow.await_args
    assert call.args[0] == "OfflineDatasetWorkflow"
    payload = call.args[1]
    assert payload["dataset_name"] == "swebench"
    assert payload["dataset_version"] == "v1"
    assert payload["dataset_source_path"] == "/tmp/swebench-v1.jsonl"
    assert payload["trigger"] == "manual"
    assert payload["requested_by"] == "unit_test"
    assert call.kwargs["id"] == "offline-datasets:swebench:v1"


def test_start_offline_ingestion_reuses_existing_workflow_on_collision() -> None:
    """Trigger client should surface existing run metadata on id collisions."""
    fake_workflow_handle = SimpleNamespace(
        describe=AsyncMock(return_value=SimpleNamespace(run_id="existing_run_001"))
    )
    fake_client = SimpleNamespace(
        start_workflow=AsyncMock(
            side_effect=WorkflowAlreadyStartedError(
                "offline-datasets:swebench:v1",
                "OfflineDatasetWorkflow",
            )
        ),
        get_workflow_handle=Mock(return_value=fake_workflow_handle),
    )
    request = StartOfflineIngestionRequest(
        dataset_name="swebench",
        dataset_version="v1",
        dataset_source_path="/tmp/swebench-v1.jsonl",
    )
    with patch("src.offline_trigger.Client.connect", new=AsyncMock(return_value=fake_client)):
        result = _run(OfflineIngestionTriggerClient().start(request))

    assert result.status == "PENDING"
    assert result.reused_existing is True
    assert result.workflow_id == "offline-datasets:swebench:v1"
    assert result.run_id == "existing_run_001"


def test_start_offline_ingestion_force_reingest_uses_unique_workflow_id() -> None:
    """Force mode should bypass canonical id and create unique workflow id."""
    fake_handle = SimpleNamespace(first_execution_run_id="run_offline_forced")
    fake_client = SimpleNamespace(
        start_workflow=AsyncMock(return_value=fake_handle),
    )
    request = StartOfflineIngestionRequest(
        dataset_name="swebench",
        dataset_version="v1",
        dataset_source_path="/tmp/swebench-v1.jsonl",
        force_reingest=True,
    )
    with patch("src.offline_trigger.Client.connect", new=AsyncMock(return_value=fake_client)):
        result = _run(OfflineIngestionTriggerClient().start(request))

    assert result.status == "PENDING"
    assert result.reused_existing is False
    assert result.workflow_id.startswith("offline-datasets:swebench:v1:force:")
    assert result.run_id == "run_offline_forced"
