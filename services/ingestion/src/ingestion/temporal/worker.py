"""Temporal worker for ingestion activities.

Run with: uv run --package ingestion python -m ingestion.temporal.worker
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from ..utilities import IngestionSettings

from .activities import (
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
from .workflows import (
    IncrementalIndexWorkflow,
    IndexBranchWorkflow,
    IndexRepositoryWorkflow,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = IngestionSettings()

    client = await Client.connect(settings.temporal_address)
    logger.info(
        "Connected to Temporal at %s, starting worker on queue %s",
        settings.temporal_address,
        settings.temporal_task_queue,
    )

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[
            IndexRepositoryWorkflow,
            IndexBranchWorkflow,
            IncrementalIndexWorkflow,
        ],
        activities=[
            ensure_repository_record,
            update_branch_status,
            git_clone_or_fetch,
            chunk_files,
            get_changed_files,
            delete_existing_chunks,
            delete_chunks_for_files,
            embed_chunk_batch,
            store_chunks,
            cleanup_staging,
        ],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
