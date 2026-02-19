"""Monthly evaluation refresh trigger path for pinned benchmark snapshots."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import re

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from .config import settings

_EVALUATION_REFRESH_WORKFLOW_PREFIX = "evaluation-refresh"
_DEFAULT_MONTHLY_CRON = "0 0 1 * *"
_TOKEN_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class StartEvaluationRefreshRequest:
    """Input payload for scheduling monthly evaluation refresh runs."""

    dataset_name: str
    dataset_version: str
    trigger: str = "monthly_schedule"
    requested_by: str = "pipeline.evaluation_refresh_trigger"
    source_event_id: str | None = None
    cron_schedule: str = _DEFAULT_MONTHLY_CRON


@dataclass(frozen=True, slots=True)
class StartEvaluationRefreshResponse:
    """Result payload returned after scheduling evaluation refresh workflow."""

    workflow_id: str
    run_id: str | None
    status: str
    reused_existing: bool
    cron_schedule: str


def evaluation_refresh_workflow_id(*, dataset_name: str, dataset_version: str) -> str:
    """Build canonical workflow id for monthly refresh of a pinned dataset slice."""
    dataset_token = _sanitize_token(dataset_name)
    version_token = _sanitize_token(dataset_version)
    if not dataset_token:
        raise ValueError("dataset_name must be non-empty")
    if not version_token:
        raise ValueError("dataset_version must be non-empty")
    return (
        f"{_EVALUATION_REFRESH_WORKFLOW_PREFIX}:"
        f"{dataset_token}:{version_token}:monthly"
    )


class EvaluationRefreshTriggerClient:
    """Temporal client facade for monthly evaluation refresh workflow scheduling."""

    def __init__(self) -> None:
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def start_monthly(
        self,
        request: StartEvaluationRefreshRequest,
    ) -> StartEvaluationRefreshResponse:
        """Start/ensure monthly evaluation refresh workflow for pinned dataset."""
        workflow_id = evaluation_refresh_workflow_id(
            dataset_name=request.dataset_name,
            dataset_version=request.dataset_version,
        )
        client = await self._get_client()
        args = {
            "dataset_name": request.dataset_name,
            "dataset_version": request.dataset_version,
            "trigger": request.trigger,
            "requested_by": request.requested_by,
            "source_event_id": request.source_event_id,
        }
        try:
            handle = await client.start_workflow(
                "EvaluationRefreshWorkflow",
                args,
                id=workflow_id,
                task_queue=settings.temporal_task_queue_offline,
                cron_schedule=request.cron_schedule,
            )
            return StartEvaluationRefreshResponse(
                workflow_id=workflow_id,
                run_id=handle.first_execution_run_id,
                status="PENDING",
                reused_existing=False,
                cron_schedule=request.cron_schedule,
            )
        except WorkflowAlreadyStartedError:
            handle = client.get_workflow_handle(workflow_id)
            run_id: str | None = None
            try:
                description = await handle.describe()
                run_id = description.run_id
            except Exception:
                run_id = None
            return StartEvaluationRefreshResponse(
                workflow_id=workflow_id,
                run_id=run_id,
                status="PENDING",
                reused_existing=True,
                cron_schedule=request.cron_schedule,
            )

    async def _get_client(self) -> Client:
        """Lazily initialize and cache a Temporal client instance."""
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                self._client = await Client.connect(
                    settings.temporal_target_host,
                    namespace=settings.temporal_namespace,
                )
        assert self._client is not None
        return self._client


def _sanitize_token(value: str) -> str:
    """Normalize one identifier token for workflow-id compatibility."""
    normalized = _TOKEN_PATTERN.sub("_", value.strip().lower())
    return normalized.strip("._-")


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI parser for monthly evaluation refresh scheduling."""
    parser = argparse.ArgumentParser(
        description=(
            "Start or ensure a monthly EvaluationRefreshWorkflow for a pinned "
            "benchmark snapshot."
        )
    )
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--cron-schedule", default=_DEFAULT_MONTHLY_CRON)
    parser.add_argument("--trigger", default="monthly_schedule")
    parser.add_argument("--requested-by", default="manual_cli")
    parser.add_argument("--source-event-id")
    return parser


async def _run_cli_async() -> int:
    """Execute CLI scheduling request and print canonical JSON response."""
    parser = _build_arg_parser()
    args = parser.parse_args()
    request = StartEvaluationRefreshRequest(
        dataset_name=args.dataset_name,
        dataset_version=args.dataset_version,
        trigger=args.trigger,
        requested_by=args.requested_by,
        source_event_id=args.source_event_id,
        cron_schedule=args.cron_schedule,
    )
    client = EvaluationRefreshTriggerClient()
    result = await client.start_monthly(request)
    print(
        json.dumps(
            {
                "workflow_id": result.workflow_id,
                "run_id": result.run_id,
                "status": result.status,
                "reused_existing": result.reused_existing,
                "cron_schedule": result.cron_schedule,
                "dataset_name": request.dataset_name,
                "dataset_version": request.dataset_version,
                "trigger": request.trigger,
                "requested_by": request.requested_by,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    """Synchronous CLI wrapper for monthly evaluation refresh scheduling."""
    return asyncio.run(_run_cli_async())


if __name__ == "__main__":
    raise SystemExit(main())
