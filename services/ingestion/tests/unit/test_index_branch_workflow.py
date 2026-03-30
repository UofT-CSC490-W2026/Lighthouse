"""Unit tests for IndexBranchWorkflow – A5 Part 4: Test Coverage Depth.

This is our most complex module: it orchestrates 7 activities with parallel
fan-out, conditional early-exit, and two-phase error handling (mark-failed +
optional staging cleanup). The 12 tests below cover:

  - Boundary conditions on embed batch sizing (tests 1-4)
  - Failure at each post-initial activity step (tests 5-7)
  - Parameter propagation through the activity chain (tests 8-10)
  - Cleanup correctness (test 11)
  - Return value formatting (test 12)

Each test explains *why* the edge case matters in its docstring.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from ingestion.temporal.activities.inputs import (
    EMBED_BATCH_SIZE,
    ChunkFilesInput,
    ChunkFilesOutput,
    CleanupInactiveChunksInput,
    CleanupStagingInput,
    EmbedBatchInput,
    FilePublishCleanup,
    GitCloneFetchInput,
    GitCloneFetchOutput,
    IndexBranchInput,
    PublishFullBranchInput,
    PublishStagedChunksOutput,
    UpdateBranchStatusInput,
)
from ingestion.temporal.activities.wiki import GenerateWikiInput
from ingestion.temporal.workflows.index_branch import IndexBranchWorkflow


@workflow.defn(name="GenerateWikiWorkflow")
class _StubGenerateWikiWorkflow:
    """Minimal stand-in for GenerateWikiWorkflow — completes instantly in tests."""

    @workflow.run
    async def run(self, input: GenerateWikiInput) -> str:
        return "wiki stub"


@workflow.defn(name="GenerateWikiWorkflow")
class _FailingGenerateWikiWorkflow:
    """Stand-in for GenerateWikiWorkflow that always fails — covers exception handling."""

    @workflow.run
    async def run(self, input: GenerateWikiInput) -> str:
        raise ApplicationError("wiki generation failed in test", non_retryable=True)


# ---------------------------------------------------------------------------
# Mock activity infrastructure (enhanced from e2e tests)
# ---------------------------------------------------------------------------


@dataclass
class ActivityTracker:
    """Records activity calls and supports conditional failures."""

    calls: list[tuple[str, object]] = field(default_factory=list)
    fail_on: str | None = None
    chunk_count: int = 10


def make_mock_activities(tracker: ActivityTracker):
    """Create mock activities wired to *tracker*.

    Enhanced over the e2e version: ``delete_existing_chunks`` now respects
    ``tracker.fail_on`` so we can test failures at every workflow step.
    """

    @activity.defn(name="update_branch_status")
    async def mock_update_branch(inp: UpdateBranchStatusInput) -> str:
        tracker.calls.append(("update_branch_status", inp))
        if tracker.fail_on == "update_branch_status":
            raise RuntimeError("mock update_branch failure")
        return inp.status

    @activity.defn(name="git_clone_or_fetch")
    async def mock_git_clone(inp: GitCloneFetchInput) -> GitCloneFetchOutput:
        tracker.calls.append(("git_clone_or_fetch", inp))
        if tracker.fail_on == "git_clone_or_fetch":
            raise RuntimeError("mock git failure")
        return GitCloneFetchOutput(
            repo_path="/tmp/repos/test", latest_commit="abc123"
        )

    @activity.defn(name="chunk_files")
    async def mock_chunk(inp: ChunkFilesInput) -> ChunkFilesOutput:
        tracker.calls.append(("chunk_files", inp))
        if tracker.fail_on == "chunk_files":
            raise RuntimeError("mock chunk failure")
        return ChunkFilesOutput(
            batch_id="batch-001", chunk_count=tracker.chunk_count
        )

    @activity.defn(name="embed_chunk_batch")
    async def mock_embed(inp: EmbedBatchInput) -> str:
        tracker.calls.append(("embed_chunk_batch", inp))
        if tracker.fail_on == "embed_chunk_batch":
            raise RuntimeError("mock embed failure")
        return f"embedded_{inp.limit}"

    @activity.defn(name="publish_full_branch")
    async def mock_publish_full(inp: PublishFullBranchInput) -> PublishStagedChunksOutput:
        tracker.calls.append(("publish_full_branch", inp))
        if tracker.fail_on == "publish_full_branch":
            raise RuntimeError("mock publish_full_branch failure")
        return PublishStagedChunksOutput(
            cleanup_targets=[
                FilePublishCleanup(file_path="a.py", previous_publish_id="legacy"),
            ]
        )

    @activity.defn(name="cleanup_inactive_chunks")
    async def mock_cleanup_inactive(inp: CleanupInactiveChunksInput) -> int:
        tracker.calls.append(("cleanup_inactive_chunks", inp))
        if tracker.fail_on == "cleanup_inactive_chunks":
            raise RuntimeError("mock cleanup_inactive failure")
        return len(inp.cleanup_targets)

    @activity.defn(name="cleanup_staging")
    async def mock_cleanup(inp: CleanupStagingInput) -> str:
        tracker.calls.append(("cleanup_staging", inp))
        return "cleaned"

    return [
        mock_update_branch,
        mock_git_clone,
        mock_chunk,
        mock_embed,
        mock_publish_full,
        mock_cleanup_inactive,
        mock_cleanup,
    ]


def _names(tracker: ActivityTracker) -> list[str]:
    return [name for name, _ in tracker.calls]


def _queue() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


def _default_input(**overrides) -> IndexBranchInput:
    defaults = dict(
        repository_id="repo-1",
        github_repo_id=1,
        repo_url="https://github.com/o/r",
        full_name="o/r",
        branch="main",
    )
    defaults.update(overrides)
    return IndexBranchInput(**defaults)


async def _run_workflow(workflow_environment, tracker, **input_overrides):
    """Helper: run IndexBranchWorkflow with the given tracker and input."""
    queue = _queue()
    async with Worker(
        workflow_environment.client,
        task_queue=queue,
        workflows=[IndexBranchWorkflow, _StubGenerateWikiWorkflow],
        activities=make_mock_activities(tracker),
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        return await workflow_environment.client.execute_workflow(
            IndexBranchWorkflow.run,
            _default_input(**input_overrides),
            id=f"test-{uuid.uuid4().hex[:8]}",
            task_queue=queue,
        )


async def _run_workflow_expect_failure(workflow_environment, tracker, **input_overrides):
    """Helper: run the workflow expecting WorkflowFailureError."""
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
                _default_input(**input_overrides),
                id=f"test-{uuid.uuid4().hex[:8]}",
                task_queue=queue,
            )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIndexBranchWorkflow:
    """12 focused tests for IndexBranchWorkflow edge cases & failure modes."""

    # ---- Boundary: embed batch sizing ----

    async def test_single_chunk_produces_one_embed_batch(self, workflow_environment):
        """Edge case: chunk_count=1.

        Why: The embed loop uses ``range(0, chunk_count, EMBED_BATCH_SIZE)``. With
        chunk_count=1 this must produce exactly one iteration at offset 0.
        A fencepost error here would either skip embedding entirely or
        produce an off-by-one offset.
        """
        tracker = ActivityTracker(chunk_count=1)
        await _run_workflow(workflow_environment, tracker)

        embed_calls = [(n, i) for n, i in tracker.calls if n == "embed_chunk_batch"]
        assert len(embed_calls) == 1
        assert embed_calls[0][1].offset == 0
        assert embed_calls[0][1].limit == EMBED_BATCH_SIZE

    async def test_exactly_embed_batch_size_chunks_one_batch(self, workflow_environment):
        """Boundary: chunk_count == EMBED_BATCH_SIZE.

        Why: ``range(0, EMBED_BATCH_SIZE, EMBED_BATCH_SIZE)`` yields ``[0]`` — exactly one batch.
        This is the upper boundary for a single batch; ``EMBED_BATCH_SIZE + 1``
        would need two.
        Off-by-one bugs commonly appear at exact-boundary values.
        """
        tracker = ActivityTracker(chunk_count=EMBED_BATCH_SIZE)
        await _run_workflow(workflow_environment, tracker)

        embed_calls = [(n, i) for n, i in tracker.calls if n == "embed_chunk_batch"]
        assert len(embed_calls) == 1
        assert embed_calls[0][1].offset == 0

    async def test_embed_batch_size_plus_one_chunks_two_batches(self, workflow_environment):
        """Boundary: chunk_count == EMBED_BATCH_SIZE + 1.

        Why: This is the smallest count that requires two embed batches.
        Verifies the loop correctly creates a second batch starting at
        offset EMBED_BATCH_SIZE.
        """
        tracker = ActivityTracker(chunk_count=EMBED_BATCH_SIZE + 1)
        await _run_workflow(workflow_environment, tracker)

        embed_calls = [(n, i) for n, i in tracker.calls if n == "embed_chunk_batch"]
        assert len(embed_calls) == 2
        offsets = sorted(i.offset for _, i in embed_calls)
        assert offsets == [0, EMBED_BATCH_SIZE]

    async def test_large_chunk_count_batch_offsets(self, workflow_environment):
        """Boundary: chunk_count=2049 produces ceil(2049 / EMBED_BATCH_SIZE) batches.

        Why: Validates batch arithmetic at scale.  The offsets must be
        ``list(range(0, 2049, EMBED_BATCH_SIZE))`` — the last batch covers only 1 chunk
        but still gets the full EMBED_BATCH_SIZE as its limit (the
        activity itself handles the short final batch).
        """
        tracker = ActivityTracker(chunk_count=2049)
        await _run_workflow(workflow_environment, tracker)

        embed_calls = [(n, i) for n, i in tracker.calls if n == "embed_chunk_batch"]
        expected_offsets = list(range(0, 2049, EMBED_BATCH_SIZE))
        assert len(embed_calls) == len(expected_offsets)
        offsets = sorted(i.offset for _, i in embed_calls)
        assert offsets == expected_offsets

    # ---- Failure modes (negative tests) ----

    async def test_publish_failure_triggers_cleanup(self, workflow_environment):
        """Failure: publish_full_branch raises after batch_id is set.

        Why: The workflow sets ``batch_id`` during chunk_files (step 3),
        then calls publish_full_branch (step 5).  If publish fails the
        exception handler must call cleanup_staging because staging rows
        already exist.
        """
        tracker = ActivityTracker(chunk_count=10, fail_on="publish_full_branch")
        await _run_workflow_expect_failure(workflow_environment, tracker)

        names = _names(tracker)
        status_calls = [i for n, i in tracker.calls if n == "update_branch_status"]
        assert any(s.status == "failed" for s in status_calls)
        assert "cleanup_staging" in names

    async def test_cleanup_inactive_failure_does_not_fail_workflow(
        self, workflow_environment
    ):
        """Failure: cleanup_inactive_chunks raises but workflow succeeds.

        Why: The stale-chunk cleanup runs after the branch is already marked
        indexed.  It is best-effort — a failure here must not roll back the
        successful index or surface as a workflow error.
        """
        tracker = ActivityTracker(chunk_count=10, fail_on="cleanup_inactive_chunks")
        result = await _run_workflow(workflow_environment, tracker)

        assert "Indexed" in result
        names = _names(tracker)
        assert "cleanup_inactive_chunks" in names
        status_calls = [i for n, i in tracker.calls if n == "update_branch_status"]
        assert status_calls[-1].status == "indexed"

    async def test_chunk_files_failure_no_cleanup(self, workflow_environment):
        """Failure: chunk_files raises before batch_id is assigned.

        Why: ``batch_id`` is set from ``chunk_result.batch_id`` AFTER
        chunk_files returns.  If chunk_files raises, batch_id stays None,
        so cleanup_staging must NOT be called (there is nothing to clean).
        This validates the ``if batch_id is not None`` guard in the
        exception handler.
        """
        tracker = ActivityTracker(fail_on="chunk_files")
        await _run_workflow_expect_failure(workflow_environment, tracker)

        names = _names(tracker)
        status_calls = [i for n, i in tracker.calls if n == "update_branch_status"]
        assert any(s.status == "failed" for s in status_calls)
        assert "cleanup_staging" not in names

    # ---- Parameter propagation (positive tests) ----

    async def test_github_token_propagated(self, workflow_environment):
        """Propagation: github_token reaches update_branch_status and git.

        Why: The token is needed for private-repo access (git clone) and
        for the initial branch-status update (which may create the branch
        record via GitHub API).  If the token is dropped, private repos
        silently fail with a 401 in production.
        """
        tracker = ActivityTracker(chunk_count=5)
        await _run_workflow(
            workflow_environment, tracker, github_token="ghp_secret123"
        )

        # Initial update_branch_status (status="indexing") should have the token
        first_status = tracker.calls[0][1]
        assert first_status.github_token == "ghp_secret123"

        # git_clone_or_fetch should have the token
        git_call = [i for n, i in tracker.calls if n == "git_clone_or_fetch"][0]
        assert git_call.github_token == "ghp_secret123"

    async def test_custom_strategies_propagated(self, workflow_environment):
        """Propagation: chunker_strategy and embedding_strategy forwarded.

        Why: The workflow accepts strategy names and must forward them to
        the correct activities.  If they are silently replaced by defaults
        the user gets sliding_window/openai instead of their chosen
        strategy, producing wrong results with no error.
        """
        tracker = ActivityTracker(chunk_count=10)
        await _run_workflow(
            workflow_environment,
            tracker,
            chunker_strategy="ast",
            embedding_strategy="cohere",
        )

        chunk_call = [i for n, i in tracker.calls if n == "chunk_files"][0]
        assert chunk_call.chunker_strategy == "ast"

        embed_calls = [i for n, i in tracker.calls if n == "embed_chunk_batch"]
        assert all(e.embedding_strategy == "cohere" for e in embed_calls)

    async def test_latest_commit_in_final_status(self, workflow_environment):
        """Propagation: latest_commit flows from git output to final status.

        Why: The final update_branch_status call must include the commit
        SHA so the system knows which commit was indexed.  The initial
        "indexing" call must NOT include it (the commit is unknown at that
        point).  Swapping these would record a stale or null commit.
        """
        tracker = ActivityTracker(chunk_count=5)
        await _run_workflow(workflow_environment, tracker)

        status_calls = [(n, i) for n, i in tracker.calls if n == "update_branch_status"]
        # First call: status="indexing", no latest_commit
        assert status_calls[0][1].status == "indexing"
        assert status_calls[0][1].latest_commit is None
        # Last call: status="indexed", latest_commit from git
        assert status_calls[-1][1].status == "indexed"
        assert status_calls[-1][1].latest_commit == "abc123"

    # ---- Cleanup correctness ----

    async def test_cleanup_receives_correct_batch_id(self, workflow_environment):
        """Cleanup: the exact batch_id from chunk_files is passed to cleanup.

        Why: If a wrong or stale batch_id is passed to cleanup_staging,
        the staging rows from the failed run leak (never deleted) while
        unrelated rows may be incorrectly purged.
        """
        tracker = ActivityTracker(chunk_count=10, fail_on="embed_chunk_batch")
        await _run_workflow_expect_failure(workflow_environment, tracker)

        cleanup_calls = [i for n, i in tracker.calls if n == "cleanup_staging"]
        assert len(cleanup_calls) == 1
        assert cleanup_calls[0].batch_id == "batch-001"

    # ---- Return value ----

    async def test_return_value_format(self, workflow_environment):
        """Return: result string includes full_name, branch, and commit SHA.

        Why: The return value is logged and used for observability.  Branch
        names with slashes (e.g. ``feature/cool``) must not be truncated.
        This also serves as a regression test for string interpolation.
        """
        tracker = ActivityTracker(chunk_count=5)
        result = await _run_workflow(
            workflow_environment,
            tracker,
            full_name="myorg/myrepo",
            branch="feature/cool",
        )
        assert result == "Indexed myorg/myrepo/feature/cool at abc123"

    async def test_wiki_generation_failure_does_not_fail_workflow(self, workflow_environment):
        """Lines 175-176: wiki generation exception is caught and logged, workflow still succeeds.

        Why: Wiki generation is best-effort. If the child workflow fails, the
        parent workflow should still mark the branch as indexed and return success.
        """
        tracker = ActivityTracker(chunk_count=5)
        queue = _queue()
        async with Worker(
            workflow_environment.client,
            task_queue=queue,
            workflows=[IndexBranchWorkflow, _FailingGenerateWikiWorkflow],
            activities=make_mock_activities(tracker),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await workflow_environment.client.execute_workflow(
                IndexBranchWorkflow.run,
                _default_input(),
                id=f"test-{uuid.uuid4().hex[:8]}",
                task_queue=queue,
            )
        # Workflow completes successfully despite wiki failure
        assert "Indexed" in result
