from __future__ import annotations

import asyncio
import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ..activities.wiki import (
        WIKI_EMBED_BATCH_SIZE,
        CleanupStagingWikiInput,
        EmbedWikiPagesInput,
        GenerateWikiInput,
        GenerateWikiPageInput,
        GenerateWikiStructureInput,
        GenerateWikiStructureOutput,
        StoreWikiPagesInput,
        UpdateWikiStatusInput,
        _flatten_structure_pages,
        cleanup_staging_wiki,
        embed_wiki_pages,
        generate_wiki_page,
        generate_wiki_structure,
        store_wiki_pages,
        update_wiki_status,
    )

_DB_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
)

_LLM_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
)


@workflow.defn
class GenerateWikiWorkflow:
    """Generate wiki documentation for an indexed repository."""

    @workflow.run
    async def run(self, input: GenerateWikiInput) -> str:
        batch_id: str | None = None
        wiki_generation_id: str | None = None

        try:
            # 1. Generate wiki structure (LLM analyzes repo)
            structure_result: GenerateWikiStructureOutput = (
                await workflow.execute_activity(
                    generate_wiki_structure,
                    GenerateWikiStructureInput(
                        repository_id=input.repository_id,
                        full_name=input.full_name,
                        branch=input.branch,
                        llm_strategy=input.llm_strategy,
                    ),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=_LLM_RETRY,
                )
            )
            batch_id = structure_result.batch_id
            wiki_generation_id = structure_result.wiki_generation_id
            structure = json.loads(structure_result.structure_json)
            pages = _flatten_structure_pages(structure)

            # 2. Generate each page in parallel (RAG + LLM)
            page_futures = []
            for page_def in pages:
                page_futures.append(
                    workflow.execute_activity(
                        generate_wiki_page,
                        GenerateWikiPageInput(
                            batch_id=batch_id,
                            wiki_generation_id=wiki_generation_id,
                            repository_id=input.repository_id,
                            branch=input.branch,
                            page_slug=page_def["slug"],
                            page_title=page_def["title"],
                            page_description=page_def.get("description", ""),
                            section_path=page_def["section_path"],
                            source_file_hints=page_def.get("source_file_hints", []),
                            llm_strategy=input.llm_strategy,
                            embedding_strategy=input.embedding_strategy,
                            embedding_model=input.embedding_model,
                        ),
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=_LLM_RETRY,
                    )
                )
            await asyncio.gather(*page_futures)

            # 3. Embed wiki pages in batches
            embed_futures = []
            for offset in range(0, structure_result.page_count, WIKI_EMBED_BATCH_SIZE):
                embed_futures.append(
                    workflow.execute_activity(
                        embed_wiki_pages,
                        EmbedWikiPagesInput(
                            batch_id=batch_id,
                            offset=offset,
                            limit=WIKI_EMBED_BATCH_SIZE,
                            embedding_strategy=input.embedding_strategy,
                            embedding_model=input.embedding_model,
                        ),
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=_LLM_RETRY,
                    )
                )
            await asyncio.gather(*embed_futures)

            # 4. Move from staging to final tables + Milvus
            await workflow.execute_activity(
                store_wiki_pages,
                StoreWikiPagesInput(
                    batch_id=batch_id,
                    wiki_generation_id=wiki_generation_id,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_DB_RETRY,
            )

            # 5. Mark as completed
            await workflow.execute_activity(
                update_wiki_status,
                UpdateWikiStatusInput(
                    wiki_generation_id=wiki_generation_id,
                    status="completed",
                    page_count=structure_result.page_count,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DB_RETRY,
            )

            return (
                f"Generated wiki for {input.full_name}/{input.branch}: "
                f"{structure_result.page_count} pages"
            )

        except Exception:
            # Mark as failed
            if wiki_generation_id is not None:
                await workflow.execute_activity(
                    update_wiki_status,
                    UpdateWikiStatusInput(
                        wiki_generation_id=wiki_generation_id,
                        status="failed",
                    ),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_DB_RETRY,
                )
            # Clean up staging
            if batch_id is not None:
                await workflow.execute_activity(
                    cleanup_staging_wiki,
                    CleanupStagingWikiInput(batch_id=batch_id),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=_DB_RETRY,
                )
            raise
