from __future__ import annotations

from pydantic import BaseModel, Field


class RepoIndexRequest(BaseModel):
    """Request payload for indexing a single repository."""

    github_repo_id: int
    repo_url: str
    full_name: str
    branches: list[str] = Field(default_factory=lambda: ["main"])
    github_token: str | None = None


class IndexRequest(BaseModel):
    """Request payload for the ingestion service index endpoint."""

    repositories: list[RepoIndexRequest]


class IndexAcceptedResponse(BaseModel):
    """Response payload from the ingestion service index endpoint."""

    status: str = "accepted"
    workflow_ids: list[str]


class BranchStatus(BaseModel):
    """Per-branch indexing state for the ingestion status endpoint."""

    branch_name: str
    status: str
    last_indexed_commit: str | None = None
    indexed_at: str | None = None


class IndexStatusResponse(BaseModel):
    """Response payload from the ingestion service status endpoint."""

    github_repo_id: int
    branches: list[BranchStatus]
