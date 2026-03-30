from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import logging
import socket
from typing import Any
from urllib.parse import urlparse

from pymilvus import MilvusClient as _MilvusClient, DataType


logger = logging.getLogger(__name__)


class CollectionField(StrEnum):
    """Milvus collection schema field names."""

    ID = "id"
    CHUNK_ID = "chunk_id"
    EMBEDDING = "embedding"
    REPOSITORY_ID = "repository_id"
    FILE_PATH = "file_path"
    BRANCH = "branch"
    PUBLISH_ID = "publish_id"


@dataclass
class MilvusSearchResult:
    chunk_id: str
    score: float
    repository_id: str
    file_path: str
    branch: str
    publish_id: str


class MilvusClient:
    """Wrapper around pymilvus for code embedding storage and retrieval."""

    def __init__(
        self,
        uri: str = "http://localhost:19530",
        collection_name: str = "embeddings",
    ) -> None:
        self.uri = uri
        self.collection_name = collection_name
        target = self._uri_target(uri)
        logger.info(
            "Milvus client init: collection=%s uri=%s target=%s",
            collection_name,
            uri,
            target,
        )
        self._log_tcp_probe(uri, collection_name)
        logger.info(
            "Milvus client init: creating pymilvus client for collection=%s",
            collection_name,
        )
        self._client = _MilvusClient(uri=uri)
        logger.info(
            "Milvus client init: pymilvus client created for collection=%s",
            collection_name,
        )

    def ensure_collection(self, dimension: int = 3072) -> None:
        """Create the collection if it does not exist."""
        if self._client.has_collection(self.collection_name):
            self._validate_existing_collection_schema()
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
        schema.add_field(CollectionField.PUBLISH_ID, DataType.VARCHAR, max_length=128)

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

    def _validate_existing_collection_schema(self) -> None:
        """Validate that an existing collection has all required fields."""
        description = self._client.describe_collection(
            collection_name=self.collection_name
        )
        field_entries = description.get("fields", [])

        existing_fields: set[str] = set()
        for field in field_entries:
            if isinstance(field, dict):
                name = field.get("name") or field.get("field_name")
            else:
                name = getattr(field, "name", None) or getattr(field, "field_name", None)
            if isinstance(name, str) and name:
                existing_fields.add(name)

        required_fields = {
            CollectionField.ID.value,
            CollectionField.CHUNK_ID.value,
            CollectionField.EMBEDDING.value,
            CollectionField.REPOSITORY_ID.value,
            CollectionField.FILE_PATH.value,
            CollectionField.BRANCH.value,
            CollectionField.PUBLISH_ID.value,
        }
        missing = sorted(required_fields - existing_fields)
        if missing:
            raise RuntimeError(
                f"Milvus collection '{self.collection_name}' is missing required "
                f"field(s): {', '.join(missing)}. Recreate the collection with the "
                "current schema before indexing."
            )

    def insert(self, records: list[dict]) -> None:
        """Batch insert records into the collection.

        Each record should have:
        id, chunk_id, embedding, repository_id, file_path, branch, publish_id
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
                CollectionField.PUBLISH_ID,
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
                        publish_id=entity[CollectionField.PUBLISH_ID],
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

        parts: list[str] = []
        for key, value in filters.items():
            if isinstance(value, dict):
                field_parts = []
                for operator, operand in value.items():
                    field_parts.append(
                        MilvusClient._build_filter_condition(key, operator, operand)
                    )
                if len(field_parts) == 1:
                    parts.append(field_parts[0])
                else:
                    parts.append(f"({' and '.join(field_parts)})")
                continue

            parts.append(
                MilvusClient._build_filter_condition(key, "==", value)
            )

        return " and ".join(parts)

    @staticmethod
    def _build_filter_condition(field: str, operator: str, value: Any) -> str:
        normalized_operator = operator.lower()
        if normalized_operator == "eq":
            normalized_operator = "=="
        elif normalized_operator == "ne":
            normalized_operator = "!="
        elif normalized_operator == "gt":
            normalized_operator = ">"
        elif normalized_operator == "lt":
            normalized_operator = "<"
        elif normalized_operator == "gte":
            normalized_operator = ">="
        elif normalized_operator == "lte":
            normalized_operator = "<="

        if normalized_operator == "in":
            if not isinstance(value, list | tuple | set):
                raise TypeError(
                    f"Filter operator 'in' for field {field!r} expects a sequence."
                )
            values = ", ".join(MilvusClient._format_filter_value(item) for item in value)
            return f"{field} in [{values}]"

        if normalized_operator not in {"==", "!=", ">", "<", ">=", "<=", "like"}:
            raise ValueError(
                f"Unsupported filter operator {operator!r} for field {field!r}."
            )

        return (
            f"{field} {normalized_operator} "
            f"{MilvusClient._format_filter_value(value)}"
        )

    @staticmethod
    def _format_filter_value(value: Any) -> str:
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, int | float):
            return str(value)
        raise TypeError(f"Unsupported filter value type: {type(value).__name__}")

    @staticmethod
    def _uri_target(uri: str) -> str:
        parsed = urlparse(uri)
        host = parsed.hostname or "<missing-host>"
        port = parsed.port or 19530
        return f"{host}:{port}"

    @staticmethod
    def _log_tcp_probe(uri: str, collection_name: str, timeout_seconds: float = 3.0) -> None:
        parsed = urlparse(uri)
        host = parsed.hostname
        port = parsed.port or 19530
        if not host:
            logger.warning(
                "Milvus client init: skipping TCP probe for collection=%s because uri=%s has no host",
                collection_name,
                uri,
            )
            return

        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                logger.info(
                    "Milvus client init: TCP probe succeeded for collection=%s target=%s:%s timeout=%ss",
                    collection_name,
                    host,
                    port,
                    timeout_seconds,
                )
        except OSError as exc:
            logger.warning(
                "Milvus client init: TCP probe failed for collection=%s target=%s:%s timeout=%ss error=%s",
                collection_name,
                host,
                port,
                timeout_seconds,
                exc,
            )
