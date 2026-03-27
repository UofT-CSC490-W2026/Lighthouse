from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ..activities import (
        EnsureRepoInput,
        IndexBranchInput,
        IndexRepoInput,
        ensure_repository_record,
    )
    from .index_branch import IndexBranchWorkflow

_DB_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
)


@workflow.defn
class IndexRepositoryWorkflow:
    """Parent workflow: ensures repo record, then fans out child workflows per branch."""

    @workflow.run
    async def run(self, input: IndexRepoInput) -> str:
        # 1. Ensure repository record exists
        repository_id = await workflow.execute_activity(
            ensure_repository_record,
            EnsureRepoInput(
                github_repo_id=input.github_repo_id,
                repo_url=input.repo_url,
                full_name=input.full_name,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DB_RETRY,
        )

        # 2. Fan out child workflows per branch
        child_futures = []
        for branch in input.branches:
            child_futures.append(
                workflow.execute_child_workflow(
                    IndexBranchWorkflow.run,
                    IndexBranchInput(
                        repository_id=repository_id,
                        github_repo_id=input.github_repo_id,
                        repo_url=input.repo_url,
                        full_name=input.full_name,
                        branch=branch,
                        github_token=input.github_token,
                        embedding_strategy=input.embedding_strategy,
                    ),
                    id=f"index-branch-{input.github_repo_id}-{branch}",
                )
            )

        results = await asyncio.gather(*child_futures, return_exceptions=True)

        # Summarize results
        successes = sum(1 for r in results if isinstance(r, str))
        failures = len(results) - successes
        return (
            f"Indexed {input.full_name}: "
            f"{successes}/{len(input.branches)} branches succeeded"
            + (f", {failures} failed" if failures else "")
        )
