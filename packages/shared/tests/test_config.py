import pytest

from shared.config import (
    BEDROCK_LLM_MODEL,
    BEDROCK_EMBEDDING_DIMENSION,
    BEDROCK_EMBEDDING_MODEL,
    CHUNK_MAX_LINES,
    CHUNK_OVERLAP_LINES,
    DEFAULT_EMBEDDING_STRATEGY,
    DEFAULT_LLM_STRATEGY,
    OPENAI_LLM_MODEL,
    OPENAI_EMBEDDING_DIMENSION,
    OPENAI_EMBEDDING_MODEL,
    default_llm_model,
    default_embedding_dimension,
    default_embedding_model,
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    LLM_MODEL,
    MILVUS_COLLECTION_NAME,
)


@pytest.mark.unit
def test_default_embedding_strategy():
    assert DEFAULT_EMBEDDING_STRATEGY == "openai"


@pytest.mark.unit
def test_default_llm_strategy():
    assert DEFAULT_LLM_STRATEGY == "bedrock"


@pytest.mark.unit
def test_provider_specific_embedding_defaults():
    assert BEDROCK_EMBEDDING_MODEL == "amazon.titan-embed-text-v2:0"
    assert BEDROCK_EMBEDDING_DIMENSION == 1024
    assert OPENAI_EMBEDDING_MODEL == "text-embedding-3-large"
    assert OPENAI_EMBEDDING_DIMENSION == 3072


@pytest.mark.unit
def test_provider_specific_llm_defaults():
    assert BEDROCK_LLM_MODEL == "us.amazon.nova-lite-v1:0"
    assert OPENAI_LLM_MODEL == "gpt-5.4-nano"


@pytest.mark.unit
def test_embedding_model():
    assert EMBEDDING_MODEL == OPENAI_EMBEDDING_MODEL


@pytest.mark.unit
def test_embedding_dimension():
    assert EMBEDDING_DIMENSION == OPENAI_EMBEDDING_DIMENSION


@pytest.mark.unit
def test_default_embedding_helpers():
    assert default_embedding_model("bedrock") == BEDROCK_EMBEDDING_MODEL
    assert default_embedding_model("openai") == OPENAI_EMBEDDING_MODEL
    assert default_embedding_dimension("bedrock") == BEDROCK_EMBEDDING_DIMENSION
    assert default_embedding_dimension("openai") == OPENAI_EMBEDDING_DIMENSION
    assert default_llm_model("bedrock") == BEDROCK_LLM_MODEL
    assert default_llm_model("openai") == OPENAI_LLM_MODEL


@pytest.mark.unit
def test_default_openai_llm_alias():
    assert LLM_MODEL == OPENAI_LLM_MODEL


@pytest.mark.unit
def test_milvus_collection_name():
    assert MILVUS_COLLECTION_NAME == "chunk_embeddings"


@pytest.mark.unit
def test_chunk_max_lines():
    assert CHUNK_MAX_LINES == 50


@pytest.mark.unit
def test_chunk_overlap_lines():
    assert CHUNK_OVERLAP_LINES == 10


@pytest.mark.unit
def test_default_embedding_model_raises_for_unknown_strategy():
    with pytest.raises(ValueError, match="Unsupported embedding strategy"):
        default_embedding_model("unknown")


@pytest.mark.unit
def test_default_embedding_dimension_raises_for_unknown_strategy():
    with pytest.raises(ValueError, match="Unsupported embedding strategy"):
        default_embedding_dimension("unknown")


@pytest.mark.unit
def test_default_llm_model_raises_for_unknown_strategy():
    with pytest.raises(ValueError, match="Unsupported llm strategy"):
        default_llm_model("unknown")
