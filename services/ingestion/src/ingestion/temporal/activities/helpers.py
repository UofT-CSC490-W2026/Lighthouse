from __future__ import annotations

from collections.abc import Callable

from db import DatabaseManager
from shared.config import EMBEDDING_DIMENSION, MILVUS_COLLECTION_NAME
from vectordb import MilvusClient

from ...utilities.config import IngestionSettings

_settings_factory: Callable[[], IngestionSettings] | None = None


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
    milvus.ensure_collection(dimension=EMBEDDING_DIMENSION)
    return milvus
