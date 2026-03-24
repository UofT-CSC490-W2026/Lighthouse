"""Temporal worker for ingestion activities.

Run with: uv run --package ingestion python -m ingestion.temporal.worker
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from ..utilities import IngestionSettings

from .activities import incremental_index_activity, index_repository_activity
from .workflows import IncrementalIndexWorkflow, IndexRepositoryWorkflow

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
        workflows=[IndexRepositoryWorkflow, IncrementalIndexWorkflow],
        activities=[index_repository_activity, incremental_index_activity],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
