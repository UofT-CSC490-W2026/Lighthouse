from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict

try:
    from shared.indexing import (
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
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.append(str(repo_root))
    from shared.indexing import (
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
    model_config = ConfigDict(extra="forbid")

    status: IndexStatus
    repo_id: str
    ref: str = "main"
    snapshot_sha: str | None = None
    job_id: str | None = None


__all__ = [
    "IndexJobStatusResponse",
    "IndexStage",
    "IndexStatus",
    "RUNTIME_INDEX_WORKFLOW_PREFIX",
    "RepoIndexStateResponse",
    "StartIndexJobRequest",
    "StartIndexJobResponse",
    "ToolIndexMetadata",
    "runtime_index_workflow_id",
    "should_reuse_runtime_workflow",
]
