from __future__ import annotations

from db import DatabaseManager
from shared.config import EMBEDDING_DIMENSION, MILVUS_COLLECTION_NAME
from vectordb import MilvusClient

from ...utilities.config import IngestionSettings


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
