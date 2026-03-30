from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ..activities import (
        EMBED_BATCH_SIZE,
        ChunkFilesInput,
        ChunkFilesOutput,
        CleanupInactiveChunksInput,
        CleanupStagingInput,
        EmbedBatchInput,
        GitCloneFetchInput,
        GitCloneFetchOutput,
        IndexBranchInput,
        PublishFullBranchInput,
        PublishStagedChunksOutput,
        UpdateBranchStatusInput,
        chunk_files,
        cleanup_inactive_chunks,
        cleanup_staging,
        embed_chunk_batch,
        git_clone_or_fetch,
        publish_full_branch,
        update_branch_status,
    )

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

            # 4. Embed chunks in batches
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
                            embedding_model=input.embedding_model,
                        ),
                        start_to_close_timeout=timedelta(minutes=10),
                        retry_policy=_EMBED_RETRY,
                    )
                )
            await asyncio.gather(*embed_futures)

            # 5. Publish staged chunks and switch active file versions
            publish_result: PublishStagedChunksOutput = await workflow.execute_activity(
                publish_full_branch,
                PublishFullBranchInput(
                    batch_id=batch_id,
                    repository_id=input.repository_id,
                    branch=input.branch,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_DB_RETRY,
            )

            # 6. Mark branch as indexed
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

            # 7. Best-effort cleanup of superseded publish versions
            if publish_result.cleanup_targets:
                try:
                    await workflow.execute_activity(
                        cleanup_inactive_chunks,
                        CleanupInactiveChunksInput(
                            repository_id=input.repository_id,
                            branch=input.branch,
                            cleanup_targets=publish_result.cleanup_targets,
                        ),
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=_DB_RETRY,
                    )
                except Exception:
                    workflow.logger.warning(
                        "Inactive chunk cleanup failed for %s/%s after publish",
                        input.full_name,
                        input.branch,
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
