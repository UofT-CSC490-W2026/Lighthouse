from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from .generate_wiki import GenerateWikiWorkflow
    from ..activities.wiki import GenerateWikiInput
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
        IncrementalPushSignalInput,
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

_IDLE_TIMEOUT = timedelta(seconds=15)


@workflow.defn
class IncrementalIndexWorkflow:
    """Branch-scoped coordinator for incremental re-indexing on push events."""

    def __init__(self) -> None:
        self._pending_push: IncrementalPushSignalInput | None = None

    @workflow.signal
    def enqueue_push(self, input: IncrementalPushSignalInput) -> None:
        """Queue the latest push for this branch, coalescing earlier pending pushes."""
        self._pending_push = input

    @workflow.run
    async def run(self, input: IncrementalIndexInput) -> str:
        current_push = IncrementalPushSignalInput(
            github_repo_id=input.github_repo_id,
            full_name=input.full_name,
            branch=input.branch,
            before_commit=input.before_commit,
            after_commit=input.after_commit,
            chunker_strategy=input.chunker_strategy,
            embedding_strategy=input.embedding_strategy,
        )

        repository_id = await workflow.execute_activity(
            ensure_repository_record,
            EnsureRepoInput(
                github_repo_id=input.github_repo_id,
                repo_url="",
                full_name=input.full_name,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DB_RETRY,
        )

        last_result = f"No changes for {input.full_name}/{input.branch}"
        while current_push is not None:
            last_result = await self._run_incremental_pass(repository_id, current_push)

            if self._pending_push is not None:
                current_push = self._pending_push
                self._pending_push = None
                continue

            try:
                await workflow.wait_condition(
                    lambda: self._pending_push is not None,
                    timeout=_IDLE_TIMEOUT,
                )
            except TimeoutError:
                break
            current_push = self._pending_push
            self._pending_push = None

        return last_result

    async def _run_incremental_pass(
        self,
        repository_id: str,
        input: IncrementalPushSignalInput,
    ) -> str:
        batch_id: str | None = None
        try:
            await workflow.execute_activity(
                update_branch_status,
                UpdateBranchStatusInput(
                    repository_id=repository_id,
                    branch=input.branch,
                    status="indexing",
                    target_commit=input.after_commit,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DB_RETRY,
            )

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

            chunk_result: ChunkFilesOutput = await workflow.execute_activity(
                chunk_files,
                ChunkFilesInput(
                    repo_path=git_result.repo_path,
                    repository_id=repository_id,
                    branch=input.branch,
                    chunker_strategy=input.chunker_strategy,
                    file_filter=changed_files,
                ),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=_DB_RETRY,
            )
            batch_id = chunk_result.batch_id

            publish_result = PublishStagedChunksOutput()
            if chunk_result.chunk_count > 0:
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
                            start_to_close_timeout=timedelta(minutes=10),
                            retry_policy=_EMBED_RETRY,
                        )
                    )
                await asyncio.gather(*embed_futures)

            publish_result = await workflow.execute_activity(
                publish_staged_chunks,
                PublishStagedChunksInput(
                    batch_id=batch_id,
                    repository_id=repository_id,
                    branch=input.branch,
                    target_commit=input.after_commit,
                    changed_files=changed_files,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_DB_RETRY,
            )

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

            # Best-effort wiki generation as a child workflow
            try:
                await workflow.execute_child_workflow(
                    GenerateWikiWorkflow.run,
                    GenerateWikiInput(
                        repository_id=repository_id,
                        github_repo_id=input.github_repo_id,
                        full_name=input.full_name,
                        branch=input.branch,
                        llm_strategy=input.llm_strategy,
                        embedding_strategy=input.embedding_strategy,
                    ),
                    id=f"wiki-{input.github_repo_id}-{input.branch}",
                )
            except Exception:
                workflow.logger.warning(
                    "Wiki generation failed for %s/%s", input.full_name, input.branch
                )

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
                    latest_commit=input.after_commit,
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
