"""Temporal client wrapper for MCP control-plane workflow orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from ..utils import settings


@dataclass(frozen=True, slots=True)
class WorkflowStartResult:
    """Result payload returned after starting a workflow execution."""

    workflow_id: str
    run_id: str | None


@dataclass(frozen=True, slots=True)
class WorkflowDescription:
    """Subset of Temporal workflow description fields used by MCP."""

    workflow_id: str
    run_id: str
    status: str
    start_time: datetime | None


class WorkflowAlreadyExistsError(RuntimeError):
    """Raised when a start request collides with an already-running workflow id."""

    def __init__(self, workflow_id: str, run_id: str | None = None):
        """Create an idempotency-collision error with optional active run id."""
        self.workflow_id = workflow_id
        self.run_id = run_id
        super().__init__(f"workflow already exists: {workflow_id}")


class TemporalClientWrapper:
    """MCP-facing Temporal client facade for runtime indexing workflows."""

    def __init__(self) -> None:
        """Initialize lazy client state and synchronization lock."""
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def start_runtime_index_workflow(
        self,
        *,
        repo_id: str,
        repo_url: str,
        ref: str,
        workflow_id: str,
        force_reindex: bool,
        github_token: str | None = None,
    ) -> WorkflowStartResult:
        """Start canonical runtime index workflow and surface idempotency collisions."""
        client = await self._get_client()
        args = {
            "repo_id": repo_id,
            "repo_url": repo_url,
            "ref": ref,
            "force_reindex": force_reindex,
        }
        if github_token:
            args["github_token"] = github_token
        try:
            handle = await client.start_workflow(
                "RuntimeIndexWorkflow",
                args,
                id=workflow_id,
                task_queue=settings.temporal_task_queue_runtime,
            )
            return WorkflowStartResult(
                workflow_id=workflow_id,
                run_id=handle.first_execution_run_id,
            )
        except WorkflowAlreadyStartedError:
            existing = await self.describe_workflow(workflow_id)
            raise WorkflowAlreadyExistsError(
                workflow_id=workflow_id,
                run_id=existing.run_id if existing else None,
            )

    async def start_forced_runtime_index_workflow(
        self,
        *,
        repo_id: str,
        repo_url: str,
        ref: str,
        base_workflow_id: str,
        github_token: str | None = None,
    ) -> WorkflowStartResult:
        """Start a unique forced runtime index workflow using a suffixed id."""
        suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        forced_workflow_id = f"{base_workflow_id}:force:{suffix}:{uuid4().hex[:8]}"
        return await self.start_runtime_index_workflow(
            repo_id=repo_id,
            repo_url=repo_url,
            ref=ref,
            workflow_id=forced_workflow_id,
            force_reindex=True,
            github_token=github_token,
        )

    async def describe_workflow(self, workflow_id: str) -> WorkflowDescription | None:
        """Describe a workflow by id, returning `None` when unavailable."""
        client = await self._get_client()
        handle = client.get_workflow_handle(workflow_id)
        try:
            description = await handle.describe()
            status_name = (
                description.status.name
                if hasattr(description.status, "name")
                else str(description.status)
            )
            return WorkflowDescription(
                workflow_id=description.id,
                run_id=description.run_id,
                status=status_name,
                start_time=description.start_time,
            )
        except Exception:
            return None

    async def _get_client(self) -> Client:
        """Lazily connect and cache a Temporal client for this process."""
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
