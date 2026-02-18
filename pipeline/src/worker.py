"""Temporal worker bootstrap for the standalone pipeline service."""

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from .activities import (
    clean_activity,
    ingest_activity,
    mental_model_activity,
    persist_runtime_index_failure_activity,
    persist_runtime_index_start_activity,
    persist_runtime_index_success_activity,
    store_activity,
    transform_activity,
)
from .config import settings
from .workflows import (
    MentalModelWorkflow,
    OfflineDatasetWorkflow,
    RuntimeIndexWorkflow,
)


async def _create_client() -> Client:
    return await Client.connect(
        settings.temporal_target_host,
        namespace=settings.temporal_namespace,
    )


async def _run_runtime_worker(client: Client) -> None:
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue_runtime,
        workflows=[RuntimeIndexWorkflow],
        activities=[
            ingest_activity,
            clean_activity,
            transform_activity,
            store_activity,
            persist_runtime_index_start_activity,
            persist_runtime_index_success_activity,
            persist_runtime_index_failure_activity,
        ],
    )
    await worker.run()


async def _run_offline_worker(client: Client) -> None:
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue_offline,
        workflows=[OfflineDatasetWorkflow],
        activities=[
            ingest_activity,
            clean_activity,
            transform_activity,
            store_activity,
        ],
    )
    await worker.run()


async def _run_mental_model_worker(client: Client) -> None:
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue_mental_model,
        workflows=[MentalModelWorkflow],
        activities=[mental_model_activity],
    )
    await worker.run()


async def main() -> None:
    client = await _create_client()
    await asyncio.gather(
        _run_runtime_worker(client),
        _run_offline_worker(client),
        _run_mental_model_worker(client),
    )


if __name__ == "__main__":
    asyncio.run(main())
