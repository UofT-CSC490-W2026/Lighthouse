from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from .activities import (
        IncrementalIndexInput,
        IndexRepoInput,
        incremental_index_activity,
        index_repository_activity,
    )


@workflow.defn
class IndexRepositoryWorkflow:
    """Temporal workflow for full repository indexing."""

    @workflow.run
    async def run(self, input: IndexRepoInput) -> str:
        return await workflow.execute_activity(
            index_repository_activity,
            input,
            start_to_close_timeout=timedelta(hours=1),
            heartbeat_timeout=timedelta(minutes=5),
        )


@workflow.defn
class IncrementalIndexWorkflow:
    """Temporal workflow for incremental re-indexing on push events."""

    @workflow.run
    async def run(self, input: IncrementalIndexInput) -> str:
        return await workflow.execute_activity(
            incremental_index_activity,
            input,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=5),
        )
