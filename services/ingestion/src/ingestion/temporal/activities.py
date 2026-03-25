from __future__ import annotations

import logging
from dataclasses import dataclass

from temporalio import activity

from ..utilities import IngestionSettings, IndexingPipeline

logger = logging.getLogger(__name__)


@dataclass
class IndexRepoInput:
    github_repo_id: int
    repo_url: str
    full_name: str
    branches: list[str]
    github_token: str | None = None


@dataclass
class IncrementalIndexInput:
    github_repo_id: int
    full_name: str
    branch: str
    before_commit: str
    after_commit: str


@activity.defn
async def index_repository_activity(input: IndexRepoInput) -> str:
    """Temporal activity that indexes a repository."""
    settings = IngestionSettings()
    pipeline = IndexingPipeline(settings)
    pipeline.initialize()
    try:
        pipeline.index_repository(
            github_repo_id=input.github_repo_id,
            repo_url=input.repo_url,
            full_name=input.full_name,
            branches=input.branches,
            github_token=input.github_token,
        )
        return f"Indexed {input.full_name} branches: {input.branches}"
    finally:
        pipeline.close()


@activity.defn
async def incremental_index_activity(input: IncrementalIndexInput) -> str:
    """Temporal activity that performs incremental indexing."""
    settings = IngestionSettings()
    pipeline = IndexingPipeline(settings)
    pipeline.initialize()
    try:
        pipeline.incremental_index(
            github_repo_id=input.github_repo_id,
            full_name=input.full_name,
            branch=input.branch,
            before_commit=input.before_commit,
            after_commit=input.after_commit,
        )
        return (
            f"Incremental index {input.full_name}/{input.branch}: "
            f"{input.before_commit[:8]}..{input.after_commit[:8]}"
        )
    finally:
        pipeline.close()
