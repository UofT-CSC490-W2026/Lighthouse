from __future__ import annotations

import sys
from pathlib import Path

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


__all__ = [
    "IndexJobStatusResponse",
    "IndexStage",
    "IndexStatus",
    "RUNTIME_INDEX_WORKFLOW_PREFIX",
    "RepoIndexStateResponse",
    "StartIndexJobRequest",
    "StartIndexJobResponse",
    "runtime_index_workflow_id",
    "should_reuse_runtime_workflow",
]
