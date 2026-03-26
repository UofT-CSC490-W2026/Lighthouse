import pytest

from testing_utils.containers import milvus_container, milvus_uri, pg_container, pg_dsn
from testing_utils.db_fixtures import db_manager, db_manager_session
from testing_utils.milvus_fixtures import milvus_client, milvus_client_session
from testing_utils.mock_embedding import MockEmbeddingProvider


@pytest.fixture
def mock_embedder():
    return MockEmbeddingProvider(dimension=8)
