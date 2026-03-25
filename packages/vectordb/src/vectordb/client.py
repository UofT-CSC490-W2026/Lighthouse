from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pymilvus import MilvusClient as _MilvusClient, DataType


class CollectionField(StrEnum):
    """Milvus collection schema field names."""

    ID = "id"
    CHUNK_ID = "chunk_id"
    EMBEDDING = "embedding"
    REPOSITORY_ID = "repository_id"
    FILE_PATH = "file_path"
    BRANCH = "branch"


@dataclass
class MilvusSearchResult:
    chunk_id: str
    score: float
    repository_id: str
    file_path: str
    branch: str


class MilvusClient:
    """Wrapper around pymilvus for code embedding storage and retrieval."""

    def __init__(
        self,
        uri: str = "http://localhost:19530",
        collection_name: str = "embeddings",
    ) -> None:
        self.uri = uri
        self.collection_name = collection_name
        self._client = _MilvusClient(uri=uri)

    def ensure_collection(self, dimension: int = 3072) -> None:
        """Create the collection if it does not exist."""
        if self._client.has_collection(self.collection_name):
            return

        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)

        # Define schema fields here.
        schema.add_field(
            CollectionField.ID, DataType.VARCHAR, is_primary=True, max_length=64
        )
        schema.add_field(CollectionField.CHUNK_ID, DataType.VARCHAR, max_length=64)
        schema.add_field(
            CollectionField.EMBEDDING, DataType.FLOAT_VECTOR, dim=dimension
        )
        schema.add_field(
            CollectionField.REPOSITORY_ID, DataType.VARCHAR, max_length=64
        )
        schema.add_field(CollectionField.FILE_PATH, DataType.VARCHAR, max_length=512)
        schema.add_field(CollectionField.BRANCH, DataType.VARCHAR, max_length=128)

        # Define indices here.
        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name=CollectionField.EMBEDDING,
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 256},
        )

        self._client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
        )

    def insert(self, records: list[dict]) -> None:
        """Batch insert records into the collection.

        Each record should have: id, chunk_id, embedding, repository_id, file_path, branch
        (see CollectionField for shared constants).
        """
        if not records:
            return
        self._client.insert(collection_name=self.collection_name, data=records)

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[MilvusSearchResult]:
        """Vector similarity search with optional filters."""
        filter_expr = self._build_filter_expr(filters)

        results = self._client.search(
            collection_name=self.collection_name,
            data=[query_embedding],
            limit=top_k,
            output_fields=[
                CollectionField.CHUNK_ID,
                CollectionField.REPOSITORY_ID,
                CollectionField.FILE_PATH,
                CollectionField.BRANCH,
            ],
            filter=filter_expr if filter_expr else "",
            search_params={"metric_type": "COSINE", "params": {"ef": 128}},
        )

        hits = []
        for result in results:
            for hit in result:
                entity = hit["entity"]
                hits.append(
                    MilvusSearchResult(
                        chunk_id=entity[CollectionField.CHUNK_ID],
                        score=hit["distance"],
                        repository_id=entity[CollectionField.REPOSITORY_ID],
                        file_path=entity[CollectionField.FILE_PATH],
                        branch=entity[CollectionField.BRANCH],
                    )
                )
        return hits

    def delete_by_filter(self, filter_expr: str) -> None:
        """Delete vectors matching a Milvus boolean expression."""
        self._client.delete(
            collection_name=self.collection_name,
            filter=filter_expr,
        )

    def drop_collection(self) -> None:
        """Drop the entire collection."""
        self._client.drop_collection(self.collection_name)

    def close(self) -> None:
        """Disconnect from Milvus."""
        self._client.close()

    @staticmethod
    def _build_filter_expr(filters: dict | None) -> str:
        if not filters:
            return ""
        parts = []
        for key, value in filters.items():
            escaped = value.replace('"', '\\"')
            parts.append(f'{key} == "{escaped}"')
        return " and ".join(parts)
