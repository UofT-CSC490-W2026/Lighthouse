"""Temporal worker bootstrap for the standalone pipeline service."""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from .activities import (
    clean_activity,
    ingest_activity,
    mental_model_activity,
    persist_runtime_index_failure_activity,
    persist_runtime_index_progress_activity,
    persist_runtime_index_start_activity,
    persist_runtime_index_success_activity,
    store_activity,
    transform_activity,
)
from .config import settings
from .connectors import MilvusConnector, PostgresConnector, S3Connector
from .workflows import (
    MentalModelWorkflow,
    OfflineDatasetWorkflow,
    RuntimeIndexWorkflow,
)

LOGGER = logging.getLogger(__name__)


class StartupValidationError(RuntimeError):
    """Raised when worker startup validation fails."""

    pass


async def _create_client() -> Client:
    """Create a Temporal client using pipeline runtime settings."""
    return await Client.connect(
        settings.temporal_target_host,
        namespace=settings.temporal_namespace,
    )


def _validate_required_settings() -> None:
    """Validate required startup configuration values."""
    errors: list[str] = []
    if not settings.temporal_target_host.strip():
        errors.append("TEMPORAL_TARGET_HOST must be non-empty")
    if not settings.temporal_namespace.strip():
        errors.append("TEMPORAL_NAMESPACE must be non-empty")
    if not settings.temporal_task_queue_runtime.strip():
        errors.append("TEMPORAL_TASK_QUEUE_RUNTIME must be non-empty")
    if not settings.temporal_task_queue_offline.strip():
        errors.append("TEMPORAL_TASK_QUEUE_OFFLINE must be non-empty")
    if not settings.temporal_task_queue_mental_model.strip():
        errors.append("TEMPORAL_TASK_QUEUE_MENTAL_MODEL must be non-empty")
    if not settings.postgres_dsn:
        errors.append("POSTGRES_DSN is required for pipeline persistence")

    if errors:
        raise StartupValidationError("; ".join(errors))


async def _validate_backend_connectivity() -> None:
    """Probe backend dependencies before worker process starts polling queues."""
    postgres = PostgresConnector(dsn=settings.postgres_dsn or "")
    try:
        await postgres.check_connection()
    finally:
        await postgres.close()

    if settings.validate_milvus_on_startup:
        milvus_password = (
            settings.milvus_password.get_secret_value()
            if settings.milvus_password is not None
            else None
        )
        milvus = MilvusConnector(
            uri=settings.milvus_uri,
            user=settings.milvus_user,
            password=milvus_password,
            database=settings.milvus_database,
        )
        await asyncio.to_thread(milvus.check_connection)
    else:
        LOGGER.info(
            "Skipping Milvus startup probe (`validate_milvus_on_startup=false`)."
        )

    if settings.validate_s3_on_startup:
        if not settings.s3_bucket:
            raise StartupValidationError(
                "validate_s3_on_startup is true but S3_BUCKET is not configured"
            )
        s3 = S3Connector(region_name=settings.aws_region)
        await asyncio.to_thread(s3.check_bucket_access, bucket=settings.s3_bucket)
    else:
        LOGGER.info("Skipping S3 startup probe (`validate_s3_on_startup=false`).")


async def _run_runtime_worker(client: Client) -> None:
    """Run the worker bound to the runtime indexing task queue."""
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
            persist_runtime_index_progress_activity,
            persist_runtime_index_success_activity,
            persist_runtime_index_failure_activity,
        ],
    )
    await worker.run()


async def _run_offline_worker(client: Client) -> None:
    """Run the worker bound to the offline dataset task queue."""
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
    """Run the worker bound to the mental-model task queue."""
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue_mental_model,
        workflows=[MentalModelWorkflow],
        activities=[mental_model_activity],
    )
    await worker.run()


async def main() -> None:
    """Start all pipeline workers concurrently in a single process."""
    _validate_required_settings()
    client = await _create_client()
    await _validate_backend_connectivity()
    await asyncio.gather(
        _run_runtime_worker(client),
        _run_offline_worker(client),
        _run_mental_model_worker(client),
    )


if __name__ == "__main__":
    asyncio.run(main())
