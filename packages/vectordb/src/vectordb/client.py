from __future__ import annotations

from pymilvus import MilvusClient as _MilvusClient, DataType


class MilvusClient:
    """Wrapper around pymilvus for code embedding storage and retrieval."""

    def __init__(
        self,
        uri: str = "http://localhost:19530",
        collection_name: str = "code_embeddings",
    ) -> None:
        self.uri = uri
        self.collection_name = collection_name
        self._client = _MilvusClient(uri=uri)

    def ensure_collection(self, dimension: int = 3072) -> None:
        """Create the collection if it does not exist."""
        if self._client.has_collection(self.collection_name):
            return

        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("chunk_id", DataType.VARCHAR, max_length=64)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dimension)
        schema.add_field("repository_id", DataType.VARCHAR, max_length=64)
        schema.add_field("file_path", DataType.VARCHAR, max_length=512)
        schema.add_field("branch", DataType.VARCHAR, max_length=128)

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
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

        Each record should have: id, chunk_id, embedding, repository_id, file_path, branch.
        """
        if not records:
            return
        self._client.insert(collection_name=self.collection_name, data=records)

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """Vector similarity search with optional filters.

        Args:
            query_embedding: The query vector.
            top_k: Number of results to return.
            filters: Optional dict with keys like repository_id, branch to filter on.

        Returns:
            List of dicts with chunk_id, score, repository_id, file_path, branch.
        """
        filter_expr = self._build_filter_expr(filters)

        results = self._client.search(
            collection_name=self.collection_name,
            data=[query_embedding],
            limit=top_k,
            output_fields=["chunk_id", "repository_id", "file_path", "branch"],
            filter=filter_expr if filter_expr else "",
            search_params={"metric_type": "COSINE", "params": {"ef": 128}},
        )

        hits = []
        for result in results:
            for hit in result:
                hits.append(
                    {
                        "chunk_id": hit["entity"]["chunk_id"],
                        "score": hit["distance"],
                        "repository_id": hit["entity"]["repository_id"],
                        "file_path": hit["entity"]["file_path"],
                        "branch": hit["entity"]["branch"],
                    }
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
