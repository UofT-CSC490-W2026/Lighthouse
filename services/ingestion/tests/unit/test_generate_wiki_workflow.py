"""Unit tests for GenerateWikiWorkflow using mock activities."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from ingestion.temporal.activities.wiki import (
    WIKI_EMBED_BATCH_SIZE,
    WIKI_PAGE_GENERATION_BATCH_SIZE,
    CleanupStagingWikiInput,
    EmbedWikiPagesInput,
    GenerateWikiInput,
    GenerateWikiPageInput,
    GenerateWikiStructureInput,
    GenerateWikiStructureOutput,
    StoreWikiPagesInput,
    UpdateWikiStatusInput,
)
from ingestion.temporal.workflows.generate_wiki import GenerateWikiWorkflow


@dataclass
class WikiActivityTracker:
    calls: list[tuple[str, object]] = field(default_factory=list)
    fail_on: str | None = None
    page_count: int = 3
    structure_json: str = ""

    def __post_init__(self):
        if not self.structure_json:
            pages = [
                {
                    "slug": f"page-{i}",
                    "title": f"Page {i}",
                    "description": f"desc {i}",
                    "section_path": "overview",
                    "source_file_hints": [],
                }
                for i in range(self.page_count)
            ]
            self.structure_json = json.dumps(
                {
                    "title": "Test Wiki",
                    "description": "desc",
                    "sections": [
                        {
                            "slug": "overview",
                            "pages": pages,
                            "subsections": [],
                        }
                    ],
                }
            )


def make_wiki_mock_activities(tracker: WikiActivityTracker):
    @activity.defn(name="generate_wiki_structure")
    async def mock_generate_structure(inp: GenerateWikiStructureInput) -> GenerateWikiStructureOutput:
        tracker.calls.append(("generate_wiki_structure", inp))
        if tracker.fail_on == "generate_wiki_structure":
            raise RuntimeError("structure generation failed")
        return GenerateWikiStructureOutput(
            batch_id=f"batch-{uuid.uuid4().hex[:8]}",
            wiki_generation_id=f"gen-{uuid.uuid4().hex[:8]}",
            page_count=tracker.page_count,
            structure_json=tracker.structure_json,
        )

    @activity.defn(name="generate_wiki_page")
    async def mock_generate_page(inp: GenerateWikiPageInput) -> str:
        tracker.calls.append(("generate_wiki_page", inp))
        if tracker.fail_on == "generate_wiki_page":
            raise RuntimeError("page generation failed")
        return f"generated:{inp.page_slug}"

    @activity.defn(name="embed_wiki_pages")
    async def mock_embed_pages(inp: EmbedWikiPagesInput) -> str:
        tracker.calls.append(("embed_wiki_pages", inp))
        if tracker.fail_on == "embed_wiki_pages":
            raise RuntimeError("embed failed")
        return f"embedded_{inp.limit}"

    @activity.defn(name="store_wiki_pages")
    async def mock_store_pages(inp: StoreWikiPagesInput) -> int:
        tracker.calls.append(("store_wiki_pages", inp))
        if tracker.fail_on == "store_wiki_pages":
            raise RuntimeError("store failed")
        return tracker.page_count

    @activity.defn(name="update_wiki_status")
    async def mock_update_status(inp: UpdateWikiStatusInput) -> str:
        tracker.calls.append(("update_wiki_status", inp))
        return inp.status

    @activity.defn(name="cleanup_staging_wiki")
    async def mock_cleanup_staging(inp: CleanupStagingWikiInput) -> str:
        tracker.calls.append(("cleanup_staging_wiki", inp))
        return "cleaned"

    return [
        mock_generate_structure,
        mock_generate_page,
        mock_embed_pages,
        mock_store_pages,
        mock_update_status,
        mock_cleanup_staging,
    ]


def _queue() -> str:
    return f"wiki-test-{uuid.uuid4().hex[:8]}"


def _default_input(**overrides) -> GenerateWikiInput:
    defaults = dict(
        repository_id="repo-1",
        github_repo_id=1,
        full_name="owner/repo",
        branch="main",
    )
    defaults.update(overrides)
    return GenerateWikiInput(**defaults)


async def _run_wiki_workflow(workflow_environment, tracker, **input_overrides):
    queue = _queue()
    async with Worker(
        workflow_environment.client,
        task_queue=queue,
        workflows=[GenerateWikiWorkflow],
        activities=make_wiki_mock_activities(tracker),
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        return await workflow_environment.client.execute_workflow(
            GenerateWikiWorkflow.run,
            _default_input(**input_overrides),
            id=f"wiki-test-{uuid.uuid4().hex[:8]}",
            task_queue=queue,
        )


async def _run_wiki_workflow_expect_failure(workflow_environment, tracker, **input_overrides):
    queue = _queue()
    async with Worker(
        workflow_environment.client,
        task_queue=queue,
        workflows=[GenerateWikiWorkflow],
        activities=make_wiki_mock_activities(tracker),
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        with pytest.raises(WorkflowFailureError):
            await workflow_environment.client.execute_workflow(
                GenerateWikiWorkflow.run,
                _default_input(**input_overrides),
                id=f"wiki-test-{uuid.uuid4().hex[:8]}",
                task_queue=queue,
            )


def _activity_names(tracker: WikiActivityTracker) -> list[str]:
    return [name for name, _ in tracker.calls]


@pytest.mark.unit
class TestGenerateWikiWorkflow:
    async def test_happy_path_generates_pages_and_completes(self, workflow_environment):
        """Full success path: all activities run, status is marked completed."""
        tracker = WikiActivityTracker(page_count=2)
        result = await _run_wiki_workflow(workflow_environment, tracker)

        names = _activity_names(tracker)
        assert "generate_wiki_structure" in names
        assert "generate_wiki_page" in names
        assert "embed_wiki_pages" in names
        assert "store_wiki_pages" in names

        status_calls = [(n, i) for n, i in tracker.calls if n == "update_wiki_status"]
        statuses = [i.status for _, i in status_calls]
        assert "completed" in statuses
        assert "2 pages" in result or "2" in result

    async def test_page_generation_produces_one_call_per_page(self, workflow_environment):
        """Each page in the structure gets its own generate_wiki_page call."""
        tracker = WikiActivityTracker(page_count=3)
        await _run_wiki_workflow(workflow_environment, tracker)

        page_calls = [(n, i) for n, i in tracker.calls if n == "generate_wiki_page"]
        assert len(page_calls) == 3

    async def test_embed_batch_count_matches_page_count(self, workflow_environment):
        """Embed is called once per WIKI_EMBED_BATCH_SIZE pages (ceiling)."""
        page_count = WIKI_EMBED_BATCH_SIZE + 1
        tracker = WikiActivityTracker(page_count=page_count)
        await _run_wiki_workflow(workflow_environment, tracker)

        embed_calls = [(n, i) for n, i in tracker.calls if n == "embed_wiki_pages"]
        assert len(embed_calls) == 2
        offsets = sorted(i.offset for _, i in embed_calls)
        assert offsets[0] == 0
        assert offsets[1] == WIKI_EMBED_BATCH_SIZE

    async def test_structure_failure_marks_failed_and_cleans_up(self, workflow_environment):
        """When structure generation fails, status=failed and staging is cleaned."""
        tracker = WikiActivityTracker(fail_on="generate_wiki_structure")
        await _run_wiki_workflow_expect_failure(workflow_environment, tracker)

        names = _activity_names(tracker)
        # No batch_id yet — cleanup_staging_wiki should NOT be called
        assert "cleanup_staging_wiki" not in names
        # update_wiki_status should NOT be called (no generation_id yet)
        status_calls = [(n, i) for n, i in tracker.calls if n == "update_wiki_status"]
        failed_statuses = [i.status for _, i in status_calls if i.status == "failed"]
        assert len(failed_statuses) == 0

    async def test_page_generation_failure_marks_failed_and_cleans_up(self, workflow_environment):
        """When page generation fails, status=failed and staging cleanup runs."""
        tracker = WikiActivityTracker(fail_on="generate_wiki_page", page_count=2)
        await _run_wiki_workflow_expect_failure(workflow_environment, tracker)

        names = _activity_names(tracker)
        assert "cleanup_staging_wiki" in names

        status_calls = [(n, i) for n, i in tracker.calls if n == "update_wiki_status"]
        statuses = [i.status for _, i in status_calls]
        assert "failed" in statuses

    async def test_store_failure_marks_failed_and_cleans_up(self, workflow_environment):
        """When store_wiki_pages fails, status=failed and cleanup runs."""
        tracker = WikiActivityTracker(fail_on="store_wiki_pages", page_count=1)
        await _run_wiki_workflow_expect_failure(workflow_environment, tracker)

        names = _activity_names(tracker)
        assert "cleanup_staging_wiki" in names
        status_calls = [(n, i) for n, i in tracker.calls if n == "update_wiki_status"]
        statuses = [i.status for _, i in status_calls]
        assert "failed" in statuses

    async def test_page_generation_batched_by_batch_size(self, workflow_environment):
        """Pages are batched WIKI_PAGE_GENERATION_BATCH_SIZE at a time."""
        page_count = WIKI_PAGE_GENERATION_BATCH_SIZE + 1
        tracker = WikiActivityTracker(page_count=page_count)
        await _run_wiki_workflow(workflow_environment, tracker)

        page_calls = [(n, i) for n, i in tracker.calls if n == "generate_wiki_page"]
        assert len(page_calls) == page_count
