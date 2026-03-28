from __future__ import annotations

import pytest

from vectordb.client import MilvusClient


@pytest.mark.unit
def test_ensure_collection_validates_existing_schema_and_raises_on_missing_publish_id():
    client = MilvusClient.__new__(MilvusClient)
    client.collection_name = "embeddings"

    class _Backend:
        def has_collection(self, collection_name: str) -> bool:
            assert collection_name == "embeddings"
            return True

        def describe_collection(self, collection_name: str) -> dict:
            assert collection_name == "embeddings"
            return {
                "fields": [
                    {"name": "id"},
                    {"name": "chunk_id"},
                    {"name": "embedding"},
                    {"name": "repository_id"},
                    {"name": "file_path"},
                    {"name": "branch"},
                ]
            }

    client._client = _Backend()

    with pytest.raises(RuntimeError, match="missing required field\\(s\\): publish_id"):
        client.ensure_collection()


@pytest.mark.unit
def test_ensure_collection_accepts_existing_schema_with_publish_id():
    client = MilvusClient.__new__(MilvusClient)
    client.collection_name = "embeddings"

    class _Backend:
        def has_collection(self, collection_name: str) -> bool:
            assert collection_name == "embeddings"
            return True

        def describe_collection(self, collection_name: str) -> dict:
            assert collection_name == "embeddings"
            return {
                "fields": [
                    {"name": "id"},
                    {"name": "chunk_id"},
                    {"name": "embedding"},
                    {"name": "repository_id"},
                    {"name": "file_path"},
                    {"name": "branch"},
                    {"name": "publish_id"},
                ]
            }

    client._client = _Backend()

    client.ensure_collection()


@pytest.mark.unit
def test_ensure_collection_accepts_object_fields_with_name_attribute():
    """Cover the else-branch where field entries are objects, not dicts."""
    client = MilvusClient.__new__(MilvusClient)
    client.collection_name = "embeddings"

    class _Field:
        def __init__(self, name: str) -> None:
            self.name = name

    class _Backend:
        def has_collection(self, collection_name: str) -> bool:
            return True

        def describe_collection(self, collection_name: str) -> dict:
            return {
                "fields": [
                    _Field("id"),
                    _Field("chunk_id"),
                    _Field("embedding"),
                    _Field("repository_id"),
                    _Field("file_path"),
                    _Field("branch"),
                    _Field("publish_id"),
                ]
            }

    client._client = _Backend()

    client.ensure_collection()
