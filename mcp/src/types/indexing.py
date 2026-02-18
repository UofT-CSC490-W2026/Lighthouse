"""MCP-local indexing payload models layered on shared canonical contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from indexing import (
    IndexJobStatusResponse,
    IndexStage,
    IndexStatus,
    RUNTIME_INDEX_WORKFLOW_PREFIX,
    RepoIndexStateResponse,
    StartIndexJobRequest,
    StartIndexJobResponse,
    runtime_index_workflow_id,
    should_reuse_runtime_workflow,
)


class ToolIndexMetadata(BaseModel):
    """Index status metadata attached to tool responses."""

    model_config = ConfigDict(extra="forbid")

    status: IndexStatus
    repo_id: str
    ref: str = "main"
    snapshot_sha: str | None = None
    job_id: str | None = None


class RetryIndexJobRequest(BaseModel):
    """Payload for forcing a retry of runtime indexing on an existing repo/ref."""

    model_config = ConfigDict(extra="forbid")

    repo_url: str | None = None
    trigger: str = "manual_retry"
    requested_by: str = "index_control_retry"


__all__ = [
    "IndexJobStatusResponse",
    "IndexStage",
    "IndexStatus",
    "RUNTIME_INDEX_WORKFLOW_PREFIX",
    "RetryIndexJobRequest",
    "RepoIndexStateResponse",
    "StartIndexJobRequest",
    "StartIndexJobResponse",
    "ToolIndexMetadata",
    "runtime_index_workflow_id",
    "should_reuse_runtime_workflow",
]
