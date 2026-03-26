from __future__ import annotations

from collections.abc import Generator

import pytest
from vectordb import MilvusClient

TEST_EMBEDDING_DIMENSION = 8


@pytest.fixture(scope="session")
def milvus_client_session(milvus_uri: str) -> Generator[MilvusClient, None, None]:
    """Session-scoped: create a MilvusClient and ensure the test collection exists."""
    client = MilvusClient(uri=milvus_uri, collection_name="test_embeddings")
    client.ensure_collection(dimension=TEST_EMBEDDING_DIMENSION)
    yield client
    client.drop_collection()
    client.close()


@pytest.fixture
def milvus_client(milvus_client_session: MilvusClient) -> Generator[MilvusClient, None, None]:
    """Function-scoped: yield the shared client, then drop/recreate collection for isolation."""
    yield milvus_client_session
    milvus_client_session.drop_collection()
    milvus_client_session.ensure_collection(dimension=TEST_EMBEDDING_DIMENSION)
