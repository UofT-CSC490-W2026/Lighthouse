from __future__ import annotations

from collections.abc import AsyncGenerator, Generator

import pytest
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment

from ingestion.temporal.activities.helpers import set_settings_factory
from ingestion.utilities.config import IngestionSettings
from testing_utils.containers import milvus_container, milvus_uri, pg_container, pg_dsn
from testing_utils.db_fixtures import db_manager, db_manager_session
from testing_utils.milvus_fixtures import milvus_client, milvus_client_session
from testing_utils.mock_embedding import MockEmbeddingProvider


@pytest.fixture
def mock_embedder():
    return MockEmbeddingProvider(dimension=8)


@pytest.fixture
def ingestion_settings(pg_dsn, milvus_uri, tmp_path) -> IngestionSettings:
    """IngestionSettings wired to testcontainer Postgres and Milvus."""
    return IngestionSettings(
        postgres_dsn=pg_dsn,
        milvus_uri=milvus_uri,
        openai_api_key="test-key",
        clone_base_dir=str(tmp_path),
        temporal_address="localhost:7233",
        temporal_task_queue="test-ingestion",
        embedding_dimension=8,
    )


@pytest.fixture
def inject_settings(ingestion_settings) -> Generator[IngestionSettings, None, None]:
    """Override get_settings() so activities use testcontainer-backed settings."""
    set_settings_factory(lambda: ingestion_settings)
    yield ingestion_settings
    set_settings_factory(None)


@pytest.fixture
def activity_environment() -> ActivityEnvironment:
    return ActivityEnvironment()


@pytest.fixture(scope="session")
async def workflow_environment() -> AsyncGenerator[WorkflowEnvironment, None]:
    env = await WorkflowEnvironment.start_time_skipping()
    yield env
    await env.shutdown()
