"""Shared Milvus runtime retrieval store primitives for MCP and pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence
from uuid import uuid4

import pymilvus
from retrieval_vectors import DEFAULT_VECTOR_DIMENSIONS

RUNTIME_CHUNK_COLLECTION = "runtime_chunks_v1"


@dataclass(frozen=True, slots=True)
class RuntimeChunkRecord:
    """One runtime chunk payload persisted into Milvus."""

    chunk_id: str
    repo_id: str
    ref: str
    snapshot_sha: str
    path: str
    chunk_index: int
    start_char: int
    end_char: int
    text: str
    text_hash: str
    embedding: list[float]


@dataclass(frozen=True, slots=True)
class RuntimeChunkHit:
    """One runtime chunk returned from Milvus semantic retrieval."""

    chunk_id: str
    repo_id: str
    ref: str
    snapshot_sha: str
    path: str
    chunk_index: int
    start_char: int
    end_char: int
    text: str
    text_hash: str
    score: float


class MilvusRuntimeRetrievalStore:
    """Read/write connector for runtime chunk vectors stored in Milvus."""

    def __init__(
        self,
        *,
        uri: str,
        user: str | None = None,
        password: str | None = None,
        database: str = "default",
        collection_name: str = RUNTIME_CHUNK_COLLECTION,
        dimensions: int = DEFAULT_VECTOR_DIMENSIONS,
    ) -> None:
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self.collection_name = collection_name
        self.dimensions = dimensions

    def check_connection(self) -> None:
        """Verify Milvus connectivity by listing collections."""
        alias = self._connect()
        try:
            pymilvus.utility.list_collections(using=alias)
        finally:
            pymilvus.connections.disconnect(alias=alias)

    def upsert_runtime_chunks(
        self,
        *,
        repo_id: str,
        ref: str,
        snapshot_sha: str,
        chunks: Sequence[RuntimeChunkRecord],
    ) -> int:
        """Replace existing repo/ref chunks and insert current runtime snapshot rows."""
        alias = self._connect()
        try:
            collection = self._ensure_collection(alias=alias)
            scope_expr = self._repo_ref_expr(repo_id=repo_id, ref=ref)
            collection.delete(expr=scope_expr)

            if not chunks:
                collection.flush()
                return 0

            rows = [
                {
                    "chunk_id": chunk.chunk_id,
                    "repo_id": chunk.repo_id,
                    "ref": chunk.ref,
                    "snapshot_sha": snapshot_sha,
                    "path": chunk.path,
                    "chunk_index": chunk.chunk_index,
                    "start_char": chunk.start_char,
                    "end_char": chunk.end_char,
                    "text": chunk.text,
                    "text_hash": chunk.text_hash,
                    "embedding": chunk.embedding,
                }
                for chunk in chunks
            ]
            collection.insert(rows)
            collection.flush()
            return len(rows)
        finally:
            pymilvus.connections.disconnect(alias=alias)

    def search_runtime_chunks(
        self,
        *,
        repo_id: str,
        ref: str,
        query_embedding: Sequence[float],
        top_k: int,
    ) -> list[RuntimeChunkHit]:
        """Query runtime chunk vectors by repo/ref scope using semantic similarity."""
        if top_k <= 0:
            return []
        if not query_embedding:
            return []

        alias = self._connect()
        try:
            if not pymilvus.utility.has_collection(self.collection_name, using=alias):
                return []

            collection = pymilvus.Collection(
                self.collection_name,
                using=alias,
            )
            collection.load()
            results = collection.search(
                data=[list(query_embedding)],
                anns_field="embedding",
                param={"metric_type": "IP", "params": {"ef": max(64, top_k * 4)}},
                limit=min(max(1, top_k), 100),
                expr=self._repo_ref_expr(repo_id=repo_id, ref=ref),
                output_fields=[
                    "chunk_id",
                    "repo_id",
                    "ref",
                    "snapshot_sha",
                    "path",
                    "chunk_index",
                    "start_char",
                    "end_char",
                    "text",
                    "text_hash",
                ],
            )

            if not results:
                return []

            return [self._as_chunk_hit(hit) for hit in results[0]]
        finally:
            pymilvus.connections.disconnect(alias=alias)

    def _connect(self) -> str:
        """Create a short-lived Milvus connection alias for one operation."""
        alias = f"rt_retrieval_{uuid4().hex[:8]}"
        pymilvus.connections.connect(
            alias=alias,
            uri=self.uri,
            user=self.user,
            password=self.password,
            db_name=self.database,
        )
        return alias

    def _ensure_collection(self, *, alias: str) -> Any:
        """Create runtime chunk collection and index if missing."""
        if not pymilvus.utility.has_collection(self.collection_name, using=alias):
            fields = [
                pymilvus.FieldSchema(
                    name="chunk_id",
                    dtype=pymilvus.DataType.VARCHAR,
                    max_length=64,
                    is_primary=True,
                ),
                pymilvus.FieldSchema(
                    name="repo_id",
                    dtype=pymilvus.DataType.VARCHAR,
                    max_length=255,
                ),
                pymilvus.FieldSchema(
                    name="ref",
                    dtype=pymilvus.DataType.VARCHAR,
                    max_length=255,
                ),
                pymilvus.FieldSchema(
                    name="snapshot_sha",
                    dtype=pymilvus.DataType.VARCHAR,
                    max_length=128,
                ),
                pymilvus.FieldSchema(
                    name="path",
                    dtype=pymilvus.DataType.VARCHAR,
                    max_length=2048,
                ),
                pymilvus.FieldSchema(
                    name="chunk_index",
                    dtype=pymilvus.DataType.INT64,
                ),
                pymilvus.FieldSchema(
                    name="start_char",
                    dtype=pymilvus.DataType.INT64,
                ),
                pymilvus.FieldSchema(
                    name="end_char",
                    dtype=pymilvus.DataType.INT64,
                ),
                pymilvus.FieldSchema(
                    name="text",
                    dtype=pymilvus.DataType.VARCHAR,
                    max_length=65535,
                ),
                pymilvus.FieldSchema(
                    name="text_hash",
                    dtype=pymilvus.DataType.VARCHAR,
                    max_length=64,
                ),
                pymilvus.FieldSchema(
                    name="embedding",
                    dtype=pymilvus.DataType.FLOAT_VECTOR,
                    dim=self.dimensions,
                ),
            ]
            schema = pymilvus.CollectionSchema(
                fields=fields,
                description="Runtime indexing chunks for MCP semantic retrieval",
                enable_dynamic_field=False,
            )
            collection = pymilvus.Collection(
                name=self.collection_name,
                schema=schema,
                using=alias,
            )
            collection.create_index(
                field_name="embedding",
                index_params={
                    "index_type": "HNSW",
                    "metric_type": "IP",
                    "params": {"M": 16, "efConstruction": 128},
                },
            )
        else:
            collection = pymilvus.Collection(
                name=self.collection_name,
                using=alias,
            )
            if not collection.indexes:
                collection.create_index(
                    field_name="embedding",
                    index_params={
                        "index_type": "HNSW",
                        "metric_type": "IP",
                        "params": {"M": 16, "efConstruction": 128},
                    },
                )
        return collection

    def _repo_ref_expr(self, *, repo_id: str, ref: str) -> str:
        """Build a Milvus boolean expression scoped to one repo/ref tuple."""
        escaped_repo_id = repo_id.replace('"', '\\"')
        escaped_ref = ref.replace('"', '\\"')
        return f'repo_id == "{escaped_repo_id}" and ref == "{escaped_ref}"'

    def _as_chunk_hit(self, raw_hit: Any) -> RuntimeChunkHit:
        """Map one raw pymilvus search hit to a typed runtime hit model."""
        payload = self._hit_payload(raw_hit)
        score = raw_hit_score(raw_hit)
        return RuntimeChunkHit(
            chunk_id=str(payload.get("chunk_id") or ""),
            repo_id=str(payload.get("repo_id") or ""),
            ref=str(payload.get("ref") or ""),
            snapshot_sha=str(payload.get("snapshot_sha") or ""),
            path=str(payload.get("path") or ""),
            chunk_index=int(payload.get("chunk_index") or 0),
            start_char=int(payload.get("start_char") or 0),
            end_char=int(payload.get("end_char") or 0),
            text=str(payload.get("text") or ""),
            text_hash=str(payload.get("text_hash") or ""),
            score=score,
        )

    def _hit_payload(self, raw_hit: Any) -> dict[str, Any]:
        """Extract an output-field mapping from a pymilvus search hit."""
        entity = getattr(raw_hit, "entity", None)
        if entity is None:
            return {}
        if isinstance(entity, dict):
            return entity
        if hasattr(entity, "to_dict"):
            value = entity.to_dict()
            if isinstance(value, dict):
                return value
        payload: dict[str, Any] = {}
        for field_name in (
            "chunk_id",
            "repo_id",
            "ref",
            "snapshot_sha",
            "path",
            "chunk_index",
            "start_char",
            "end_char",
            "text",
            "text_hash",
        ):
            try:
                payload[field_name] = entity.get(field_name)
            except Exception:
                continue
        return payload


def raw_hit_score(raw_hit: Any) -> float:
    """Read score/distance from a raw pymilvus hit in a version-tolerant way."""
    score = getattr(raw_hit, "score", None)
    if score is None:
        score = getattr(raw_hit, "distance", None)
    if score is None:
        return 0.0
    try:
        return float(score)
    except (TypeError, ValueError):
        return 0.0
