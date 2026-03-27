from __future__ import annotations

import logging
import operator
from dataclasses import asdict
from functools import reduce
from typing import cast

from db import Chunk, DatabaseManager, IndexedFile, Repository
from embedding import EmbeddingProvider
from shared.schemas.search import CodeSnippet, SearchRequest, SearchResult
from vectordb import MilvusClient

from .search_strategy import SearchStrategy

logger = logging.getLogger(__name__)


class HybridSearchStrategy(SearchStrategy[SearchRequest, SearchResult]):
    """Hybrid search combining vector similarity and PostgreSQL full-text search."""

    VECTOR_OVERFETCH_MULTIPLIER = 4

    def __init__(
        self,
        db_manager: DatabaseManager,
        milvus: MilvusClient,
        embedder: EmbeddingProvider,
    ) -> None:
        self.db_manager = db_manager
        self.milvus = milvus
        self.embedder = embedder

    async def search(self, request: SearchRequest) -> SearchResult:
        repo_id: str | None = None
        with self.db_manager.connection_context():
            repo = Repository.get_or_none(
                Repository.github_repo_id == request.github_repo_id
            )
            if repo:
                repo_id = repo.id

        # Build filters for Milvus
        filters: dict[str, str] = {}
        if repo_id:
            filters["repository_id"] = repo_id
        if request.branch:
            filters["branch"] = request.branch

        # 1. Vector search
        vector_results: list[dict] = []
        try:
            query_embedding = self.embedder.embed_single(request.query)
            raw_vector_results = [
                asdict(r)
                for r in self.milvus.search(
                    query_embedding=query_embedding,
                    # Over-fetch because stale-publish hits may be filtered out
                    # before fusion.
                    top_k=request.top_k * self.VECTOR_OVERFETCH_MULTIPLIER,
                    filters=filters if filters else None,
                )
            ]
            vector_results = self._filter_vector_results(raw_vector_results)
        except Exception:
            logger.exception("Vector search failed, falling back to keyword-only")

        # 2. Keyword search
        keyword_results = self._keyword_search(request, repo_id)

        # 3. Reciprocal Rank Fusion
        fused = self._rrf_fusion(vector_results, keyword_results, k=60)

        # 4. Get top_k chunk IDs and fetch full content
        top_chunk_ids = [r["chunk_id"] for r in fused[: request.top_k]]

        if not top_chunk_ids:
            return SearchResult(snippets=[], query=request.query, total_results=0)

        # Fetch full chunks from postgres
        with self.db_manager.connection_context():
            chunks = (
                Chunk.select()
                .where(Chunk.id.in_(top_chunk_ids)) #type: ignore
            )
            chunk_map = {c.id: c for c in chunks}

        # Build ordered snippets matching fusion order
        score_map = {r["chunk_id"]: r["score"] for r in fused}
        snippets: list[CodeSnippet] = []
        for chunk_id in top_chunk_ids:
            chunk = chunk_map.get(chunk_id)
            if chunk is None:
                continue
            snippets.append(
                CodeSnippet(
                    file_path=chunk.file_path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content=chunk.content,
                    language=chunk.language,
                    score=score_map.get(chunk_id, 0.0),
                )
            )

        return SearchResult(
            snippets=snippets,
            query=request.query,
            total_results=len(fused),
        )

    def _keyword_search(
        self, request: SearchRequest, repo_id: str | None
    ) -> list[dict]:
        """Execute PostgreSQL full-text search on chunks.content."""
        with self.db_manager.connection_context():
            # Build raw SQL for full-text search (Peewee's ORM doesn't
            # handle tsvector/tsquery parameterization cleanly)
            conditions = [
                "to_tsvector('english', chunks.content) @@ plainto_tsquery('english', %s)"
            ]
            params: list[str] = [request.query, request.query]  # one for WHERE, one for ts_rank

            if repo_id:
                conditions.append("chunks.repository_id = %s")
                params.append(repo_id)
            if request.branch:
                conditions.append("chunks.branch = %s")
                params.append(request.branch)

            where_clause = " AND ".join(conditions)
            sql = f"""
                SELECT chunks.id, chunks.file_path,
                       ts_rank(to_tsvector('english', chunks.content),
                               plainto_tsquery('english', %s)) as rank
                FROM chunks
                LEFT JOIN indexed_files
                  ON indexed_files.repository_id = chunks.repository_id
                 AND indexed_files.branch_name = chunks.branch
                 AND indexed_files.file_path = chunks.file_path
                WHERE {where_clause}
                  AND (
                    (indexed_files.active_publish_id IS NOT NULL
                     AND chunks.publish_id = indexed_files.active_publish_id)
                    OR
                    (indexed_files.active_publish_id IS NULL
                     AND indexed_files.id IS NULL
                     AND chunks.publish_id = 'legacy')
                  )
                ORDER BY rank DESC
                LIMIT %s
            """
            params.append(str(request.top_k * 2))

            results = []
            for row in Chunk.raw(sql, *params):
                results.append(
                    {
                        "chunk_id": row.id,
                        "score": float(row.rank),
                    }
                )
            return results

    def _filter_vector_results(self, vector_results: list[dict]) -> list[dict]:
        if not vector_results:
            return []

        active_publish_by_file = self._get_active_publish_map(
            [
                cast(tuple[str, str, str], (r["repository_id"], r["branch"], r["file_path"]))
                for r in vector_results
            ]
        )

        filtered = []
        for result in vector_results:
            key = cast(
                tuple[str, str, str],
                (result["repository_id"], result["branch"], result["file_path"]),
            )
            if key not in active_publish_by_file:
                if result["publish_id"] == "legacy":
                    filtered.append(result)
                continue

            active_publish_id = active_publish_by_file[key]
            if active_publish_id is None:
                continue

            if result["publish_id"] == active_publish_id:
                filtered.append(result)

        return filtered

    def _get_active_publish_map(
        self, file_keys: list[tuple[str, str, str]]
    ) -> dict[tuple[str, str, str], str | None]:
        if not file_keys:
            return {}

        with self.db_manager.connection_context():
            predicate = reduce(
                operator.or_,
                (
                    (IndexedFile.repository == repository_id)
                    & (IndexedFile.branch_name == branch)
                    & (IndexedFile.file_path == file_path)
                    for repository_id, branch, file_path in file_keys
                ),
            )
            rows = (
                IndexedFile.select(
                    IndexedFile.repository,
                    IndexedFile.branch_name,
                    IndexedFile.file_path,
                    IndexedFile.active_publish_id,
                )
                .where(predicate)
            )
            return {
                (row.repository_id, row.branch_name, row.file_path): row.active_publish_id
                for row in rows
            }

    @staticmethod
    def _rrf_fusion(
        vector_results: list[dict],
        keyword_results: list[dict],
        k: int = 60,
    ) -> list[dict]:
        """Reciprocal Rank Fusion combining two ranked lists."""
        scores: dict[str, float] = {}
        chunk_data: dict[str, dict] = {}

        for rank, result in enumerate(vector_results):
            cid = result["chunk_id"]
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank + 1)
            chunk_data[cid] = result

        for rank, result in enumerate(keyword_results):
            cid = result["chunk_id"]
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank + 1)
            if cid not in chunk_data:
                chunk_data[cid] = result

        # Sort by fused score descending
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        return [
            {**chunk_data[cid], "score": scores[cid]}
            for cid in sorted_ids
        ]
