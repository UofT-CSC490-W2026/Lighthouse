"""Shared constants used by ingestion and search services."""

DEFAULT_EMBEDDING_STRATEGY = "openai"
BEDROCK_EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
BEDROCK_EMBEDDING_DIMENSION = 1024
OPENAI_EMBEDDING_MODEL = "text-embedding-3-large"
OPENAI_EMBEDDING_DIMENSION = 3072
EMBEDDING_MODEL = OPENAI_EMBEDDING_MODEL
EMBEDDING_DIMENSION = OPENAI_EMBEDDING_DIMENSION
MILVUS_COLLECTION_NAME = "chunk_embeddings"
CHUNK_MAX_LINES = 50
CHUNK_OVERLAP_LINES = 10


def default_embedding_model(strategy: str) -> str:
    normalized = strategy.strip().lower()
    if normalized == "bedrock":
        return BEDROCK_EMBEDDING_MODEL
    if normalized == "openai":
        return OPENAI_EMBEDDING_MODEL
    raise ValueError(f"Unsupported embedding strategy: {strategy!r}")


def default_embedding_dimension(strategy: str) -> int:
    normalized = strategy.strip().lower()
    if normalized == "bedrock":
        return BEDROCK_EMBEDDING_DIMENSION
    if normalized == "openai":
        return OPENAI_EMBEDDING_DIMENSION
    raise ValueError(f"Unsupported embedding strategy: {strategy!r}")
