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
