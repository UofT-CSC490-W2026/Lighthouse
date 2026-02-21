"""Milvus-backed retrieval backend shared by MCP domain services."""

from __future__ import annotations

import asyncio

from retrieval_vectors import embed_text
from runtime_retrieval import MilvusRuntimeRetrievalStore, RuntimeChunkHit

from ..utils import get_logger, settings


class RetrievalBackendService:
    """Provide semantic runtime chunk retrieval over Milvus for MCP services."""

    def __init__(
        self,
        *,
        store: MilvusRuntimeRetrievalStore | None = None,
    ) -> None:
        self.log = get_logger(__name__)
        self.store = store or MilvusRuntimeRetrievalStore(
            uri=settings.milvus_uri,
            user=settings.milvus_user,
            password=(
                settings.milvus_password.get_secret_value()
                if settings.milvus_password is not None
                else None
            ),
            database=settings.milvus_database,
            collection_name=settings.runtime_milvus_collection,
            dimensions=settings.runtime_milvus_vector_dimensions,
        )

    async def search(
        self,
        *,
        repo_id: str,
        ref: str,
        query_text: str,
        top_k: int,
        path_hint: str | None = None,
    ) -> list[RuntimeChunkHit]:
        """Run one semantic retrieval query over runtime chunks for a repo/ref."""
        cleaned_query = query_text.strip()
        if not cleaned_query:
            return []
        if top_k <= 0:
            return []

        query_embedding = embed_text(
            cleaned_query,
            dimensions=settings.runtime_milvus_vector_dimensions,
        )

        try:
            hits = await asyncio.to_thread(
                self.store.search_runtime_chunks,
                repo_id=repo_id,
                ref=ref,
                query_embedding=query_embedding,
                top_k=top_k,
            )
        except Exception as exc:
            self.log.warning(
                "Milvus semantic search failed for repo=%s ref=%s: %s",
                repo_id,
                ref,
                exc,
            )
            return []

        if path_hint:
            normalized = path_hint.strip().lower()
            hits = sorted(
                hits,
                key=lambda hit: (
                    0 if hit.path.lower() == normalized else 1,
                    -hit.score,
                    hit.path,
                    hit.chunk_index,
                ),
            )
        else:
            hits = sorted(
                hits,
                key=lambda hit: (-hit.score, hit.path, hit.chunk_index),
            )

        return hits[:top_k]
