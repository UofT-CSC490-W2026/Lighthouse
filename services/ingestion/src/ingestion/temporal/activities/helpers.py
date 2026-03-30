from __future__ import annotations

from collections.abc import Callable

from db import DatabaseManager
from shared.config import (
    MILVUS_COLLECTION_NAME,
    WIKI_MILVUS_COLLECTION_NAME,
    default_embedding_dimension,
)
from vectordb import MilvusClient

from ...utilities.config import IngestionSettings

_settings_factory: Callable[[], IngestionSettings] | None = None
EMBEDDING_DIMENSION = default_embedding_dimension("bedrock")


def set_settings_factory(factory: Callable[[], IngestionSettings] | None) -> None:
    """Override the default IngestionSettings constructor (for testing)."""
    global _settings_factory
    _settings_factory = factory


def get_settings() -> IngestionSettings:
    """Return settings from the override factory or the default constructor."""
    if _settings_factory is not None:
        return _settings_factory()
    return IngestionSettings()


def make_db(settings: IngestionSettings) -> DatabaseManager:
    """Create and connect a DatabaseManager."""
    db = DatabaseManager(settings.postgres_dsn)
    db.connect()
    return db


def make_milvus(settings: IngestionSettings) -> MilvusClient:
    """Create a MilvusClient and ensure the collection exists."""
    milvus = MilvusClient(
        uri=settings.milvus_uri,
        collection_name=MILVUS_COLLECTION_NAME,
    )
    dimension = (
        settings.embedding_dimension
        or EMBEDDING_DIMENSION
        or default_embedding_dimension(settings.embedding_strategy)
    )
    milvus.ensure_collection(dimension=dimension)
    return milvus


def make_wiki_milvus(settings: IngestionSettings) -> MilvusClient:
    """Create a MilvusClient for the wiki embeddings collection."""
    milvus = MilvusClient(
        uri=settings.milvus_uri,
        collection_name=WIKI_MILVUS_COLLECTION_NAME,
    )
    dimension = settings.embedding_dimension or default_embedding_dimension(
        settings.embedding_strategy
    )
    milvus.ensure_collection(dimension=dimension)
    return milvus
