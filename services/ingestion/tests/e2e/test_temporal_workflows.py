"""Workflow orchestration tests using WorkflowEnvironment with mocked activities.

These tests verify the correct activity call sequence, fan-out, error handling,
and early exit paths for all three workflows. No real Postgres or Milvus.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from ingestion.temporal.activities.inputs import (
    EMBED_BATCH_SIZE,
    CleanupInactiveChunksInput,
    ChunkFilesInput,
    ChunkFilesOutput,
    CleanupStagingInput,
    EmbedBatchInput,
    EnsureRepoInput,
    FilePublishCleanup,
    GetChangedFilesInput,
    GitCloneFetchInput,
    GitCloneFetchOutput,
    IndexBranchInput,
    IncrementalIndexInput,
    IncrementalPushSignalInput,
    PublishFullBranchInput,
    PublishStagedChunksInput,
    PublishStagedChunksOutput,
    UpdateBranchStatusInput,
)
from ingestion.temporal.activities.wiki import GenerateWikiInput
from ingestion.temporal.workflows.index_branch import IndexBranchWorkflow
from ingestion.temporal.workflows.incremental import IncrementalIndexWorkflow


@workflow.defn(name="GenerateWikiWorkflow")
class _StubGenerateWikiWorkflow:
    """Minimal stand-in for GenerateWikiWorkflow — completes instantly in tests."""

    @workflow.run
    async def run(self, input: GenerateWikiInput) -> str:
        return "wiki stub"


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
    delay_on: str | None = None
    delay_seconds: float = 0.0


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
        if tracker.delay_on == "git_clone_or_fetch":
            await asyncio.sleep(tracker.delay_seconds)
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

    @activity.defn(name="publish_staged_chunks")
    async def mock_publish(input: PublishStagedChunksInput) -> PublishStagedChunksOutput:
        tracker.calls.append(("publish_staged_chunks", input))
        if tracker.fail_on == "publish_staged_chunks":
            raise RuntimeError("mock publish failure")
        return PublishStagedChunksOutput(
            cleanup_targets=[
                FilePublishCleanup(file_path=file_path, previous_publish_id="legacy")
                for file_path in input.changed_files
            ]
        )

    @activity.defn(name="publish_full_branch")
    async def mock_publish_full(input: PublishFullBranchInput) -> PublishStagedChunksOutput:
        tracker.calls.append(("publish_full_branch", input))
        if tracker.fail_on == "publish_full_branch":
            raise RuntimeError("mock publish_full_branch failure")
        return PublishStagedChunksOutput(
            cleanup_targets=[
                FilePublishCleanup(file_path="a.py", previous_publish_id="legacy"),
            ]
        )

    @activity.defn(name="cleanup_inactive_chunks")
    async def mock_cleanup_inactive(input: CleanupInactiveChunksInput) -> int:
        tracker.calls.append(("cleanup_inactive_chunks", input))
        if tracker.fail_on == "cleanup_inactive_chunks":
            raise RuntimeError("mock cleanup inactive failure")
        return len(input.cleanup_targets)

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
        mock_publish,
        mock_publish_full,
        mock_cleanup_inactive,
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
            workflows=[IndexBranchWorkflow, _StubGenerateWikiWorkflow],
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
        assert "embed_chunk_batch" in names
        assert "publish_full_branch" in names
        assert "cleanup_inactive_chunks" in names
        assert "delete_existing_chunks" not in names
        assert "store_chunks" not in names
        # Final status update (indexed) comes before best-effort cleanup
        status_calls = [inp for name, inp in tracker.calls if name == "update_branch_status"]
        assert status_calls[-1].status == "indexed"

    async def test_zero_chunks_early_exit(self, workflow_environment):
        tracker = ActivityTracker(chunk_count=0)
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IndexBranchWorkflow, _StubGenerateWikiWorkflow],
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
        assert "publish_full_branch" not in names
        assert "embed_chunk_batch" not in names
        assert "cleanup_inactive_chunks" not in names
        assert "delete_existing_chunks" not in names
        assert "store_chunks" not in names
        # Should still mark as indexed
        status_calls = [inp for name, inp in tracker.calls if name == "update_branch_status"]
        assert status_calls[-1].status == "indexed"

    async def test_parallel_embed_batches(self, workflow_environment):
        tracker = ActivityTracker(chunk_count=1024)
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IndexBranchWorkflow, _StubGenerateWikiWorkflow],
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
        assert len(embed_calls) == 1024 // EMBED_BATCH_SIZE
        offsets = sorted(inp.offset for _, inp in embed_calls)
        assert offsets == list(range(0, 1024, EMBED_BATCH_SIZE))

    async def test_failure_before_chunking(self, workflow_environment):
        tracker = ActivityTracker(fail_on="git_clone_or_fetch")
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IndexBranchWorkflow, _StubGenerateWikiWorkflow],
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
            workflows=[IndexBranchWorkflow, _StubGenerateWikiWorkflow],
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
            workflows=[IncrementalIndexWorkflow, _StubGenerateWikiWorkflow],
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
        assert "chunk_files" in names
        assert "embed_chunk_batch" in names
        assert "publish_staged_chunks" in names
        assert "cleanup_inactive_chunks" in names

    async def test_no_changed_files_early_exit(self, workflow_environment):
        tracker = ActivityTracker(changed_files=[])
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IncrementalIndexWorkflow, _StubGenerateWikiWorkflow],
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
        assert "chunk_files" not in names
        # Should still mark indexed
        status_calls = [inp for name, inp in tracker.calls if name == "update_branch_status"]
        assert any(s.status == "indexed" for s in status_calls)

    async def test_signal_queues_second_push_on_same_workflow(self, workflow_environment):
        tracker = ActivityTracker(
            chunk_count=1,
            changed_files=["a.py"],
            delay_on="git_clone_or_fetch",
            delay_seconds=1.0,
        )
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IncrementalIndexWorkflow, _StubGenerateWikiWorkflow],
            activities=make_mock_activities(tracker),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await workflow_environment.client.start_workflow(
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
            await handle.signal(
                IncrementalIndexWorkflow.enqueue_push,
                IncrementalPushSignalInput(
                    github_repo_id=1,
                    full_name="o/r",
                    branch="main",
                    before_commit="bbb22222",
                    after_commit="ccc33333",
                ),
            )
            result = await handle.result()

        assert "bbb22222..ccc33333" in result
        changed_inputs = [inp for name, inp in tracker.calls if name == "get_changed_files"]
        assert [inp.after_commit for inp in changed_inputs] == ["bbb22222", "ccc33333"]
        status_calls = [inp for name, inp in tracker.calls if name == "update_branch_status"]
        assert status_calls[-1].latest_commit == "ccc33333"

    async def test_changed_files_but_zero_chunks(self, workflow_environment):
        tracker = ActivityTracker(chunk_count=0, changed_files=["deleted.py"])
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IncrementalIndexWorkflow, _StubGenerateWikiWorkflow],
            activities=make_mock_activities(tracker),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
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
        # embed and store should be skipped when chunk_count=0
        assert "embed_chunk_batch" not in names
        assert "publish_staged_chunks" in names
        # But should still be marked indexed
        status_calls = [inp for name, inp in tracker.calls if name == "update_branch_status"]
        assert any(s.status == "indexed" for s in status_calls)

    async def test_failure_cleans_staging(self, workflow_environment):
        tracker = ActivityTracker(chunk_count=5, fail_on="publish_staged_chunks")
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IncrementalIndexWorkflow, _StubGenerateWikiWorkflow],
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

    async def test_publish_failure_before_switch_never_runs_stale_cleanup(
        self, workflow_environment
    ):
        tracker = ActivityTracker(
            chunk_count=5,
            changed_files=["a.py"],
            fail_on="publish_staged_chunks",
        )
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IncrementalIndexWorkflow, _StubGenerateWikiWorkflow],
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
        assert "publish_staged_chunks" in names
        assert "cleanup_staging" in names
        assert "cleanup_inactive_chunks" not in names
        status_calls = [inp for name, inp in tracker.calls if name == "update_branch_status"]
        assert status_calls[-1].status == "failed"

    async def test_cleanup_inactive_failure_does_not_fail_workflow(
        self, workflow_environment
    ):
        tracker = ActivityTracker(
            chunk_count=5,
            changed_files=["a.py"],
            fail_on="cleanup_inactive_chunks",
        )
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IncrementalIndexWorkflow, _StubGenerateWikiWorkflow],
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
        names = _activity_names(tracker)
        assert "publish_staged_chunks" in names
        assert "cleanup_inactive_chunks" in names
        status_calls = [inp for name, inp in tracker.calls if name == "update_branch_status"]
        assert status_calls[-1].status == "indexed"
