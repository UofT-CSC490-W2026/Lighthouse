import pytest

from shared.config import (
    CHUNK_MAX_LINES,
    CHUNK_OVERLAP_LINES,
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    MILVUS_COLLECTION_NAME,
)


@pytest.mark.unit
def test_embedding_model():
    assert EMBEDDING_MODEL == "text-embedding-3-large"


@pytest.mark.unit
def test_embedding_dimension():
    assert EMBEDDING_DIMENSION == 3072


@pytest.mark.unit
def test_milvus_collection_name():
    assert MILVUS_COLLECTION_NAME == "chunk_embeddings"


@pytest.mark.unit
def test_chunk_max_lines():
    assert CHUNK_MAX_LINES == 50


@pytest.mark.unit
def test_chunk_overlap_lines():
    assert CHUNK_OVERLAP_LINES == 10
