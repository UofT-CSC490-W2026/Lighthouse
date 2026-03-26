"""Workflow orchestration tests using WorkflowEnvironment with mocked activities.

These tests verify the correct activity call sequence, fan-out, error handling,
and early exit paths for all three workflows. No real Postgres or Milvus.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from ingestion.temporal.activities.inputs import (
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
    IndexBranchInput,
    IndexRepoInput,
    IncrementalIndexInput,
    StoreChunksInput,
    UpdateBranchStatusInput,
)
from ingestion.temporal.workflows.index_branch import IndexBranchWorkflow
from ingestion.temporal.workflows.index_repository import IndexRepositoryWorkflow
from ingestion.temporal.workflows.incremental import IncrementalIndexWorkflow


# ---------------------------------------------------------------------------
# Mock activity infrastructure
# ---------------------------------------------------------------------------


@dataclass
class ActivityTracker:
    """Records activity calls and supports conditional failures."""

    calls: list[tuple[str, object]] = field(default_factory=list)
    fail_on: str | None = None
    chunk_count: int = 10
    changed_files: list[str] = field(default_factory=lambda: ["a.py", "b.py"])


def make_mock_activities(tracker: ActivityTracker):
    """Create a list of mock activity functions wired to the given tracker."""

    @activity.defn(name="ensure_repository_record")
    async def mock_ensure_repo(input: EnsureRepoInput) -> str:
        tracker.calls.append(("ensure_repository_record", input))
        if tracker.fail_on == "ensure_repository_record":
            raise RuntimeError("mock ensure_repo failure")
        return "repo-id-123"

    @activity.defn(name="update_branch_status")
    async def mock_update_branch(input: UpdateBranchStatusInput) -> str:
        tracker.calls.append(("update_branch_status", input))
        if tracker.fail_on == "update_branch_status":
            raise RuntimeError("mock update_branch failure")
        return input.status

    @activity.defn(name="git_clone_or_fetch")
    async def mock_git_clone(input: GitCloneFetchInput) -> GitCloneFetchOutput:
        tracker.calls.append(("git_clone_or_fetch", input))
        if tracker.fail_on == "git_clone_or_fetch":
            raise RuntimeError("mock git failure")
        return GitCloneFetchOutput(
            repo_path="/tmp/repos/test", latest_commit="abc123"
        )

    @activity.defn(name="get_changed_files")
    async def mock_get_changed(input: GetChangedFilesInput) -> list[str]:
        tracker.calls.append(("get_changed_files", input))
        return tracker.changed_files

    @activity.defn(name="chunk_files")
    async def mock_chunk(input: ChunkFilesInput) -> ChunkFilesOutput:
        tracker.calls.append(("chunk_files", input))
        if tracker.fail_on == "chunk_files":
            raise RuntimeError("mock chunk failure")
        return ChunkFilesOutput(
            batch_id="batch-001", chunk_count=tracker.chunk_count
        )

    @activity.defn(name="embed_chunk_batch")
    async def mock_embed(input: EmbedBatchInput) -> str:
        tracker.calls.append(("embed_chunk_batch", input))
        if tracker.fail_on == "embed_chunk_batch":
            raise RuntimeError("mock embed failure")
        return f"embedded_{input.limit}"

    @activity.defn(name="delete_existing_chunks")
    async def mock_delete(input: DeleteChunksInput) -> int:
        tracker.calls.append(("delete_existing_chunks", input))
        return 5

    @activity.defn(name="delete_chunks_for_files")
    async def mock_delete_files(input: DeleteChunksForFilesInput) -> int:
        tracker.calls.append(("delete_chunks_for_files", input))
        return len(input.file_paths)

    @activity.defn(name="store_chunks")
    async def mock_store(input: StoreChunksInput) -> int:
        tracker.calls.append(("store_chunks", input))
        if tracker.fail_on == "store_chunks":
            raise RuntimeError("mock store failure")
        return tracker.chunk_count

    @activity.defn(name="cleanup_staging")
    async def mock_cleanup(input: CleanupStagingInput) -> str:
        tracker.calls.append(("cleanup_staging", input))
        return "cleaned"

    return [
        mock_ensure_repo,
        mock_update_branch,
        mock_git_clone,
        mock_get_changed,
        mock_chunk,
        mock_embed,
        mock_delete,
        mock_delete_files,
        mock_store,
        mock_cleanup,
    ]


def _activity_names(tracker: ActivityTracker) -> list[str]:
    """Return just the activity names from the call log."""
    return [name for name, _ in tracker.calls]


def _queue() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# IndexBranchWorkflow tests
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestIndexBranchWorkflow:
    async def test_happy_path(self, workflow_environment):
        tracker = ActivityTracker(chunk_count=10)
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IndexBranchWorkflow],
            activities=make_mock_activities(tracker),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await workflow_environment.client.execute_workflow(
                IndexBranchWorkflow.run,
                IndexBranchInput(
                    repository_id="repo-1",
                    github_repo_id=1,
                    repo_url="https://github.com/o/r",
                    full_name="o/r",
                    branch="main",
                ),
                id=f"test-{uuid.uuid4().hex[:8]}",
                task_queue=queue,
            )
        assert "Indexed o/r/main at abc123" == result
        names = _activity_names(tracker)
        assert names[0] == "update_branch_status"
        assert names[1] == "git_clone_or_fetch"
        assert names[2] == "chunk_files"
        assert names[3] == "delete_existing_chunks"
        assert "embed_chunk_batch" in names
        assert "store_chunks" in names
        # Final status update
        assert names[-1] == "update_branch_status"
        last_status = tracker.calls[-1][1]
        assert last_status.status == "indexed"

    async def test_zero_chunks_early_exit(self, workflow_environment):
        tracker = ActivityTracker(chunk_count=0)
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IndexBranchWorkflow],
            activities=make_mock_activities(tracker),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await workflow_environment.client.execute_workflow(
                IndexBranchWorkflow.run,
                IndexBranchInput(
                    repository_id="repo-1",
                    github_repo_id=1,
                    repo_url="https://github.com/o/r",
                    full_name="o/r",
                    branch="main",
                ),
                id=f"test-{uuid.uuid4().hex[:8]}",
                task_queue=queue,
            )
        assert "No chunks" in result
        names = _activity_names(tracker)
        assert "delete_existing_chunks" not in names
        assert "embed_chunk_batch" not in names
        assert "store_chunks" not in names
        # Should still mark as indexed
        last_status = tracker.calls[-1][1]
        assert last_status.status == "indexed"

    async def test_parallel_embed_batches(self, workflow_environment):
        tracker = ActivityTracker(chunk_count=1024)
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IndexBranchWorkflow],
            activities=make_mock_activities(tracker),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await workflow_environment.client.execute_workflow(
                IndexBranchWorkflow.run,
                IndexBranchInput(
                    repository_id="repo-1",
                    github_repo_id=1,
                    repo_url="https://github.com/o/r",
                    full_name="o/r",
                    branch="main",
                ),
                id=f"test-{uuid.uuid4().hex[:8]}",
                task_queue=queue,
            )
        embed_calls = [
            (name, inp) for name, inp in tracker.calls if name == "embed_chunk_batch"
        ]
        assert len(embed_calls) == 2
        offsets = sorted(inp.offset for _, inp in embed_calls)
        assert offsets == [0, 512]

    async def test_failure_before_chunking(self, workflow_environment):
        tracker = ActivityTracker(fail_on="git_clone_or_fetch")
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IndexBranchWorkflow],
            activities=make_mock_activities(tracker),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await workflow_environment.client.execute_workflow(
                    IndexBranchWorkflow.run,
                    IndexBranchInput(
                        repository_id="repo-1",
                        github_repo_id=1,
                        repo_url="https://github.com/o/r",
                        full_name="o/r",
                        branch="main",
                    ),
                    id=f"test-{uuid.uuid4().hex[:8]}",
                    task_queue=queue,
                )
        names = _activity_names(tracker)
        assert "update_branch_status" in names
        # Should mark failed
        status_calls = [inp for name, inp in tracker.calls if name == "update_branch_status"]
        assert any(s.status == "failed" for s in status_calls)
        # Should NOT cleanup staging (batch_id was never set)
        assert "cleanup_staging" not in names

    async def test_failure_after_chunking_cleans_up(self, workflow_environment):
        tracker = ActivityTracker(chunk_count=10, fail_on="embed_chunk_batch")
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IndexBranchWorkflow],
            activities=make_mock_activities(tracker),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await workflow_environment.client.execute_workflow(
                    IndexBranchWorkflow.run,
                    IndexBranchInput(
                        repository_id="repo-1",
                        github_repo_id=1,
                        repo_url="https://github.com/o/r",
                        full_name="o/r",
                        branch="main",
                    ),
                    id=f"test-{uuid.uuid4().hex[:8]}",
                    task_queue=queue,
                )
        names = _activity_names(tracker)
        status_calls = [inp for name, inp in tracker.calls if name == "update_branch_status"]
        assert any(s.status == "failed" for s in status_calls)
        assert "cleanup_staging" in names


# ---------------------------------------------------------------------------
# IndexRepositoryWorkflow tests
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestIndexRepositoryWorkflow:
    async def test_single_branch_success(self, workflow_environment):
        tracker = ActivityTracker(chunk_count=5)
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IndexRepositoryWorkflow, IndexBranchWorkflow],
            activities=make_mock_activities(tracker),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await workflow_environment.client.execute_workflow(
                IndexRepositoryWorkflow.run,
                IndexRepoInput(
                    github_repo_id=1,
                    repo_url="https://github.com/o/r",
                    full_name="o/r",
                    branches=["main"],
                ),
                id=f"test-{uuid.uuid4().hex[:8]}",
                task_queue=queue,
            )
        assert "1/1 branches succeeded" in result
        assert "ensure_repository_record" == _activity_names(tracker)[0]

    async def test_multi_branch_fan_out(self, workflow_environment):
        tracker = ActivityTracker(chunk_count=5)
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IndexRepositoryWorkflow, IndexBranchWorkflow],
            activities=make_mock_activities(tracker),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await workflow_environment.client.execute_workflow(
                IndexRepositoryWorkflow.run,
                IndexRepoInput(
                    github_repo_id=1,
                    repo_url="https://github.com/o/r",
                    full_name="o/r",
                    branches=["main", "dev"],
                ),
                id=f"test-{uuid.uuid4().hex[:8]}",
                task_queue=queue,
            )
        assert "2/2 branches succeeded" in result

    async def test_partial_failure(self, workflow_environment):
        """One branch fails (git error), other succeeds."""
        call_count = {"git": 0}

        @activity.defn(name="git_clone_or_fetch")
        async def git_fail_second(input: GitCloneFetchInput) -> GitCloneFetchOutput:
            call_count["git"] += 1
            # Fail for the second branch
            if call_count["git"] > 1:
                raise RuntimeError("git failure on second branch")
            return GitCloneFetchOutput(
                repo_path="/tmp/repos/test", latest_commit="abc123"
            )

        tracker = ActivityTracker(chunk_count=5)
        mock_acts = make_mock_activities(tracker)
        # Replace git activity with the one that fails on second call
        mock_acts = [a for a in mock_acts if a.__name__ != "mock_git_clone"]
        mock_acts.append(git_fail_second)

        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IndexRepositoryWorkflow, IndexBranchWorkflow],
            activities=mock_acts,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await workflow_environment.client.execute_workflow(
                IndexRepositoryWorkflow.run,
                IndexRepoInput(
                    github_repo_id=1,
                    repo_url="https://github.com/o/r",
                    full_name="o/r",
                    branches=["main", "dev"],
                ),
                id=f"test-{uuid.uuid4().hex[:8]}",
                task_queue=queue,
            )
        assert "1 failed" in result


# ---------------------------------------------------------------------------
# IncrementalIndexWorkflow tests
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestIncrementalIndexWorkflow:
    async def test_happy_path(self, workflow_environment):
        tracker = ActivityTracker(chunk_count=5, changed_files=["a.py", "b.py"])
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IncrementalIndexWorkflow],
            activities=make_mock_activities(tracker),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await workflow_environment.client.execute_workflow(
                IncrementalIndexWorkflow.run,
                IncrementalIndexInput(
                    github_repo_id=1,
                    full_name="o/r",
                    branch="main",
                    before_commit="aaa11111",
                    after_commit="bbb22222",
                ),
                id=f"test-{uuid.uuid4().hex[:8]}",
                task_queue=queue,
            )
        assert "aaa11111..bbb22222" in result
        assert "2 files" in result
        names = _activity_names(tracker)
        assert "ensure_repository_record" in names
        assert "get_changed_files" in names
        assert "delete_chunks_for_files" in names
        assert "chunk_files" in names
        assert "embed_chunk_batch" in names
        assert "store_chunks" in names

    async def test_no_changed_files_early_exit(self, workflow_environment):
        tracker = ActivityTracker(changed_files=[])
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IncrementalIndexWorkflow],
            activities=make_mock_activities(tracker),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await workflow_environment.client.execute_workflow(
                IncrementalIndexWorkflow.run,
                IncrementalIndexInput(
                    github_repo_id=1,
                    full_name="o/r",
                    branch="main",
                    before_commit="aaa11111",
                    after_commit="bbb22222",
                ),
                id=f"test-{uuid.uuid4().hex[:8]}",
                task_queue=queue,
            )
        assert "No changes" in result
        names = _activity_names(tracker)
        assert "delete_chunks_for_files" not in names
        assert "chunk_files" not in names
        # Should still mark indexed
        status_calls = [inp for name, inp in tracker.calls if name == "update_branch_status"]
        assert any(s.status == "indexed" for s in status_calls)

    async def test_changed_files_but_zero_chunks(self, workflow_environment):
        tracker = ActivityTracker(chunk_count=0, changed_files=["deleted.py"])
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IncrementalIndexWorkflow],
            activities=make_mock_activities(tracker),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await workflow_environment.client.execute_workflow(
                IncrementalIndexWorkflow.run,
                IncrementalIndexInput(
                    github_repo_id=1,
                    full_name="o/r",
                    branch="main",
                    before_commit="aaa11111",
                    after_commit="bbb22222",
                ),
                id=f"test-{uuid.uuid4().hex[:8]}",
                task_queue=queue,
            )
        names = _activity_names(tracker)
        # embed and store should be skipped when chunk_count=0
        assert "embed_chunk_batch" not in names
        assert "store_chunks" not in names
        # But should still be marked indexed
        status_calls = [inp for name, inp in tracker.calls if name == "update_branch_status"]
        assert any(s.status == "indexed" for s in status_calls)

    async def test_failure_cleans_staging(self, workflow_environment):
        tracker = ActivityTracker(chunk_count=5, fail_on="store_chunks")
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IncrementalIndexWorkflow],
            activities=make_mock_activities(tracker),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await workflow_environment.client.execute_workflow(
                    IncrementalIndexWorkflow.run,
                    IncrementalIndexInput(
                        github_repo_id=1,
                        full_name="o/r",
                        branch="main",
                        before_commit="aaa11111",
                        after_commit="bbb22222",
                    ),
                    id=f"test-{uuid.uuid4().hex[:8]}",
                    task_queue=queue,
                )
        names = _activity_names(tracker)
        status_calls = [inp for name, inp in tracker.calls if name == "update_branch_status"]
        assert any(s.status == "failed" for s in status_calls)
        assert "cleanup_staging" in names
