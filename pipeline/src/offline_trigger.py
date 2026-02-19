"""Manual/offline trigger path for benchmark snapshot ingestion workflows."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from uuid import uuid4

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from .config import settings

_OFFLINE_WORKFLOW_PREFIX = "offline-datasets"
_TOKEN_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class StartOfflineIngestionRequest:
    """Input payload for starting one offline benchmark ingestion workflow."""

    dataset_name: str
    dataset_version: str
    dataset_source_path: str
    trigger: str = "manual"
    requested_by: str = "pipeline.offline_trigger"
    source_event_id: str | None = None
    force_reingest: bool = False


@dataclass(frozen=True, slots=True)
class StartOfflineIngestionResponse:
    """Result payload returned after requesting offline ingestion start."""

    workflow_id: str
    run_id: str | None
    status: str
    reused_existing: bool


def offline_dataset_workflow_id(*, dataset_name: str, dataset_version: str) -> str:
    """Build canonical idempotent workflow id for one benchmark snapshot."""
    dataset_token = _sanitize_token(dataset_name)
    version_token = _sanitize_token(dataset_version)
    if not dataset_token:
        raise ValueError("dataset_name must be non-empty")
    if not version_token:
        raise ValueError("dataset_version must be non-empty")
    return f"{_OFFLINE_WORKFLOW_PREFIX}:{dataset_token}:{version_token}"


class OfflineIngestionTriggerClient:
    """Temporal client facade for starting offline benchmark ingestion runs."""

    def __init__(self) -> None:
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def start(self, request: StartOfflineIngestionRequest) -> StartOfflineIngestionResponse:
        """Start an offline dataset workflow with canonical idempotency behavior."""
        client = await self._get_client()
        workflow_id = offline_dataset_workflow_id(
            dataset_name=request.dataset_name,
            dataset_version=request.dataset_version,
        )
        if request.force_reingest:
            suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            workflow_id = f"{workflow_id}:force:{suffix}:{uuid4().hex[:8]}"

        args = {
            "dataset_name": request.dataset_name,
            "dataset_version": request.dataset_version,
            "dataset_source_path": request.dataset_source_path,
            "trigger": request.trigger,
            "requested_by": request.requested_by,
            "source_event_id": request.source_event_id,
        }
        try:
            handle = await client.start_workflow(
                "OfflineDatasetWorkflow",
                args,
                id=workflow_id,
                task_queue=settings.temporal_task_queue_offline,
            )
            return StartOfflineIngestionResponse(
                workflow_id=workflow_id,
                run_id=handle.first_execution_run_id,
                status="PENDING",
                reused_existing=False,
            )
        except WorkflowAlreadyStartedError:
            handle = client.get_workflow_handle(workflow_id)
            run_id: str | None = None
            try:
                description = await handle.describe()
                run_id = description.run_id
            except Exception:
                run_id = None
            return StartOfflineIngestionResponse(
                workflow_id=workflow_id,
                run_id=run_id,
                status="PENDING",
                reused_existing=True,
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
    """Build CLI parser for starting offline benchmark ingestion workflows."""
    parser = argparse.ArgumentParser(
        description="Start an OfflineDatasetWorkflow benchmark snapshot ingestion run.",
    )
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--dataset-source-path", required=True)
    parser.add_argument("--trigger", default="manual")
    parser.add_argument("--requested-by", default="manual_cli")
    parser.add_argument("--source-event-id")
    parser.add_argument("--force-reingest", action="store_true")
    return parser


async def _run_cli_async() -> int:
    """Execute CLI workflow-start request and print canonical JSON output."""
    parser = _build_arg_parser()
    args = parser.parse_args()
    request = StartOfflineIngestionRequest(
        dataset_name=args.dataset_name,
        dataset_version=args.dataset_version,
        dataset_source_path=args.dataset_source_path,
        trigger=args.trigger,
        requested_by=args.requested_by,
        source_event_id=args.source_event_id,
        force_reingest=args.force_reingest,
    )
    client = OfflineIngestionTriggerClient()
    result = await client.start(request)
    payload = {
        "workflow_id": result.workflow_id,
        "run_id": result.run_id,
        "status": result.status,
        "reused_existing": result.reused_existing,
        "trigger": request.trigger,
        "requested_by": request.requested_by,
        "dataset_name": request.dataset_name,
        "dataset_version": request.dataset_version,
        "dataset_source_path": request.dataset_source_path,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main() -> int:
    """Synchronous CLI wrapper for running offline benchmark trigger flow."""
    return asyncio.run(_run_cli_async())


if __name__ == "__main__":
    raise SystemExit(main())
