"""Shared constants used by ingestion and search services."""

EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSION = 3072
MILVUS_COLLECTION_NAME = "chunk_embeddings"
CHUNK_MAX_LINES = 50
CHUNK_OVERLAP_LINES = 10

LLM_MODEL = "gpt-4.1"
WIKI_MILVUS_COLLECTION_NAME = "wiki_embeddings"
