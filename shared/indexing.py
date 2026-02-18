from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class IndexStatus(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"
    STALE = "STALE"


class IndexStage(StrEnum):
    INGEST = "INGEST"
    CLEAN = "CLEAN"
    TRANSFORM = "TRANSFORM"
    STORE = "STORE"
    MENTAL_MODEL = "MENTAL_MODEL"


RUNTIME_INDEX_WORKFLOW_PREFIX = "runtime-index"


def runtime_index_workflow_id(repo_id: str, ref: str = "main") -> str:
    normalized_repo_id = repo_id.strip()
    normalized_ref = (ref or "main").strip()
    if not normalized_repo_id:
        raise ValueError("repo_id must be non-empty")
    if not normalized_ref:
        raise ValueError("ref must be non-empty")
    return (
        f"{RUNTIME_INDEX_WORKFLOW_PREFIX}:{normalized_repo_id}:{normalized_ref}"
    )


def should_reuse_runtime_workflow(force_reindex: bool) -> bool:
    return not force_reindex


class StartIndexJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_id: str
    repo_url: str
    ref: str = "main"
    trigger: str
    requested_by: str
    force_reindex: bool = False


class StartIndexJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    workflow_id: str
    status: IndexStatus


class IndexJobStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    repo_id: str
    ref: str = "main"
    status: IndexStatus
    stage: IndexStage | None = None
    progress_pct: int = Field(0, ge=0, le=100)
    workflow_id: str
    error_code: str | None = None
    error_message: str | None = None


class RepoIndexStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_id: str
    ref: str = "main"
    status: IndexStatus
    snapshot_sha: str | None = None
    active_job_id: str | None = None
