from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ..activities import (
        EMBED_BATCH_SIZE,
        CleanupInactiveChunksInput,
        ChunkFilesInput,
        ChunkFilesOutput,
        CleanupStagingInput,
        EmbedBatchInput,
        EnsureRepoInput,
        GetChangedFilesInput,
        GitCloneFetchInput,
        GitCloneFetchOutput,
        IncrementalIndexInput,
        PublishStagedChunksInput,
        PublishStagedChunksOutput,
        UpdateBranchStatusInput,
        chunk_files,
        cleanup_inactive_chunks,
        cleanup_staging,
        embed_chunk_batch,
        ensure_repository_record,
        get_changed_files,
        git_clone_or_fetch,
        publish_staged_chunks,
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

            # 4. Chunk changed files -> staging
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

            publish_result = PublishStagedChunksOutput()
            if chunk_result.chunk_count > 0:
                # 5. Embed in batches
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

            # 6. Publish staged chunks and switch active file versions
            publish_result = await workflow.execute_activity(
                publish_staged_chunks,
                PublishStagedChunksInput(
                    batch_id=batch_id,
                    repository_id=repository_id,
                    branch=input.branch,
                    changed_files=changed_files,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_DB_RETRY,
            )

            # 7. Mark indexed
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

            # 8. Best-effort cleanup of superseded publishes
            if publish_result.cleanup_targets:
                try:
                    await workflow.execute_activity(
                        cleanup_inactive_chunks,
                        CleanupInactiveChunksInput(
                            repository_id=repository_id,
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
