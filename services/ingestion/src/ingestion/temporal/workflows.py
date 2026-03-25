from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from .activities import (
        EMBED_BATCH_SIZE,
        ChunkFilesInput,
        ChunkFilesOutput,
        CleanupStagingInput,
        DeleteChunksForFilesInput,
        DeleteChunksInput,
        EmbedBatchInput,
        EnsureRepoInput,
        GetChangedFilesInput,
        GitCloneFetchInput,
        GitCloneFetchOutput,
        IncrementalIndexInput,
        IndexBranchInput,
        IndexRepoInput,
        StoreChunksInput,
        UpdateBranchStatusInput,
        chunk_files,
        cleanup_staging,
        delete_chunks_for_files,
        delete_existing_chunks,
        embed_chunk_batch,
        ensure_repository_record,
        get_changed_files,
        git_clone_or_fetch,
        store_chunks,
        update_branch_status,
    )


# --- Retry policies ---

_DB_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
)

_GIT_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
)

_EMBED_RETRY = RetryPolicy(
    maximum_attempts=5,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
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


@workflow.defn
class IndexBranchWorkflow:
    """Child workflow: indexes a single branch through granular activities."""

    @workflow.run
    async def run(self, input: IndexBranchInput) -> str:
        batch_id: str | None = None
        try:
            # 1. Mark branch as indexing
            await workflow.execute_activity(
                update_branch_status,
                UpdateBranchStatusInput(
                    repository_id=input.repository_id,
                    branch=input.branch,
                    status="indexing",
                    github_token=input.github_token,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DB_RETRY,
            )

            # 2. Clone or fetch
            git_result: GitCloneFetchOutput = await workflow.execute_activity(
                git_clone_or_fetch,
                GitCloneFetchInput(
                    repo_url=input.repo_url,
                    repo_dir_name=str(input.github_repo_id),
                    branch=input.branch,
                    github_token=input.github_token,
                ),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=_GIT_RETRY,
            )

            # 3. Chunk all files -> staging table
            chunk_result: ChunkFilesOutput = await workflow.execute_activity(
                chunk_files,
                ChunkFilesInput(
                    repo_path=git_result.repo_path,
                    repository_id=input.repository_id,
                    branch=input.branch,
                    chunker_strategy=input.chunker_strategy,
                ),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=_DB_RETRY,
            )
            batch_id = chunk_result.batch_id

            if chunk_result.chunk_count == 0:
                await workflow.execute_activity(
                    update_branch_status,
                    UpdateBranchStatusInput(
                        repository_id=input.repository_id,
                        branch=input.branch,
                        status="indexed",
                        latest_commit=git_result.latest_commit,
                    ),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_DB_RETRY,
                )
                return f"No chunks for {input.full_name}/{input.branch}"

            # 4. Delete existing chunks
            await workflow.execute_activity(
                delete_existing_chunks,
                DeleteChunksInput(
                    repository_id=input.repository_id,
                    branch=input.branch,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_DB_RETRY,
            )

            # 5. Embed chunks in batches
            embed_futures = []
            for offset in range(0, chunk_result.chunk_count, EMBED_BATCH_SIZE):
                embed_futures.append(
                    workflow.execute_activity(
                        embed_chunk_batch,
                        EmbedBatchInput(
                            batch_id=batch_id,
                            offset=offset,
                            limit=EMBED_BATCH_SIZE,
                            embedding_strategy=input.embedding_strategy,
                        ),
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=_EMBED_RETRY,
                    )
                )
            await asyncio.gather(*embed_futures)

            # 6. Move from staging to final tables + Milvus
            await workflow.execute_activity(
                store_chunks,
                StoreChunksInput(batch_id=batch_id),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_DB_RETRY,
            )

            # 7. Mark branch as indexed
            await workflow.execute_activity(
                update_branch_status,
                UpdateBranchStatusInput(
                    repository_id=input.repository_id,
                    branch=input.branch,
                    status="indexed",
                    latest_commit=git_result.latest_commit,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DB_RETRY,
            )

            return f"Indexed {input.full_name}/{input.branch} at {git_result.latest_commit}"

        except Exception:
            # Mark branch as failed
            await workflow.execute_activity(
                update_branch_status,
                UpdateBranchStatusInput(
                    repository_id=input.repository_id,
                    branch=input.branch,
                    status="failed",
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DB_RETRY,
            )
            # Clean up staging if we got that far
            if batch_id is not None:
                await workflow.execute_activity(
                    cleanup_staging,
                    CleanupStagingInput(batch_id=batch_id),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=_DB_RETRY,
                )
            raise


@workflow.defn
class IncrementalIndexWorkflow:
    """Workflow for incremental re-indexing on push events."""

    @workflow.run
    async def run(self, input: IncrementalIndexInput) -> str:
        settings_input = EnsureRepoInput(
            github_repo_id=input.github_repo_id,
            repo_url="",
            full_name=input.full_name,
        )
        # Resolve repository_id
        repository_id = await workflow.execute_activity(
            ensure_repository_record,
            settings_input,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DB_RETRY,
        )

        batch_id: str | None = None
        try:
            # 1. Mark branch as indexing
            await workflow.execute_activity(
                update_branch_status,
                UpdateBranchStatusInput(
                    repository_id=repository_id,
                    branch=input.branch,
                    status="indexing",
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DB_RETRY,
            )

            # 2. Clone or fetch
            git_result: GitCloneFetchOutput = await workflow.execute_activity(
                git_clone_or_fetch,
                GitCloneFetchInput(
                    repo_url="",
                    repo_dir_name=str(input.github_repo_id),
                    branch=input.branch,
                ),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=_GIT_RETRY,
            )

            # 3. Get changed files
            changed_files: list[str] = await workflow.execute_activity(
                get_changed_files,
                GetChangedFilesInput(
                    repo_path=git_result.repo_path,
                    before_commit=input.before_commit,
                    after_commit=input.after_commit,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_DB_RETRY,
            )

            if not changed_files:
                await workflow.execute_activity(
                    update_branch_status,
                    UpdateBranchStatusInput(
                        repository_id=repository_id,
                        branch=input.branch,
                        status="indexed",
                        latest_commit=input.after_commit,
                    ),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_DB_RETRY,
                )
                return f"No changes for {input.full_name}/{input.branch}"

            # 4. Delete chunks for changed files
            await workflow.execute_activity(
                delete_chunks_for_files,
                DeleteChunksForFilesInput(
                    repository_id=repository_id,
                    branch=input.branch,
                    file_paths=changed_files,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_DB_RETRY,
            )

            # 5. Chunk changed files -> staging
            chunk_result: ChunkFilesOutput = await workflow.execute_activity(
                chunk_files,
                ChunkFilesInput(
                    repo_path=git_result.repo_path,
                    repository_id=repository_id,
                    branch=input.branch,
                    file_filter=changed_files,
                ),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=_DB_RETRY,
            )
            batch_id = chunk_result.batch_id

            if chunk_result.chunk_count > 0:
                # 6. Embed in batches
                embed_futures = []
                for offset in range(0, chunk_result.chunk_count, EMBED_BATCH_SIZE):
                    embed_futures.append(
                        workflow.execute_activity(
                            embed_chunk_batch,
                            EmbedBatchInput(
                                batch_id=batch_id,
                                offset=offset,
                                limit=EMBED_BATCH_SIZE,
                            ),
                            start_to_close_timeout=timedelta(minutes=5),
                            retry_policy=_EMBED_RETRY,
                        )
                    )
                await asyncio.gather(*embed_futures)

                # 7. Store chunks
                await workflow.execute_activity(
                    store_chunks,
                    StoreChunksInput(batch_id=batch_id),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=_DB_RETRY,
                )

            # 8. Mark indexed
            await workflow.execute_activity(
                update_branch_status,
                UpdateBranchStatusInput(
                    repository_id=repository_id,
                    branch=input.branch,
                    status="indexed",
                    latest_commit=input.after_commit,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DB_RETRY,
            )

            return (
                f"Incremental index {input.full_name}/{input.branch}: "
                f"{input.before_commit[:8]}..{input.after_commit[:8]} "
                f"({len(changed_files)} files)"
            )

        except Exception:
            await workflow.execute_activity(
                update_branch_status,
                UpdateBranchStatusInput(
                    repository_id=repository_id,
                    branch=input.branch,
                    status="failed",
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DB_RETRY,
            )
            if batch_id is not None:
                await workflow.execute_activity(
                    cleanup_staging,
                    CleanupStagingInput(batch_id=batch_id),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=_DB_RETRY,
                )
            raise
