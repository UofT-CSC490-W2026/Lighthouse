from __future__ import annotations

import logging

from db import CodeChunk, DatabaseManager, Repository
from shared.config import EMBEDDING_MODEL
from shared.schemas.search import CodeSnippet, SearchRequest, SearchResult
from vectordb import MilvusClient

from .search_strategy import SearchStrategy

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Lightweight embedding client for the search service."""

    def __init__(self, api_key: str, model: str = EMBEDDING_MODEL) -> None:
        import openai

        self.client = openai.OpenAI(api_key=api_key)
        self.model = model

    def embed(self, text: str) -> list[float]:
        response = self.client.embeddings.create(input=[text], model=self.model)
        return response.data[0].embedding


class HybridSearchStrategy(SearchStrategy):
    """Hybrid search combining vector similarity and PostgreSQL full-text search."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        milvus: MilvusClient,
        embedder: EmbeddingClient,
    ) -> None:
        self.db_manager = db_manager
        self.milvus = milvus
        self.embedder = embedder

    async def search(self, request: SearchRequest) -> SearchResult:
        repo_id: str | None = None
        if request.repository_name:
            with self.db_manager.connection_context():
                repo = Repository.get_or_none(
                    Repository.repo_id == request.repository_name
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
            query_embedding = self.embedder.embed(request.query)
            vector_results = self.milvus.search(
                query_embedding=query_embedding,
                top_k=request.top_k * 2,
                filters=filters if filters else None,
            )
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
                CodeChunk.select()
                .where(CodeChunk.id.in_(top_chunk_ids))
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
        """Execute PostgreSQL full-text search on code_chunks.content."""
        with self.db_manager.connection_context():
            # Build raw SQL for full-text search (Peewee's ORM doesn't
            # handle tsvector/tsquery parameterization cleanly)
            conditions = [
                "to_tsvector('english', content) @@ plainto_tsquery('english', %s)"
            ]
            params: list[str] = [request.query, request.query]  # one for WHERE, one for ts_rank

            if repo_id:
                conditions.append("repository_id = %s")
                params.append(repo_id)
            if request.branch:
                conditions.append("branch = %s")
                params.append(request.branch)

            where_clause = " AND ".join(conditions)
            sql = f"""
                SELECT id, file_path,
                       ts_rank(to_tsvector('english', content),
                               plainto_tsquery('english', %s)) as rank
                FROM code_chunks
                WHERE {where_clause}
                ORDER BY rank DESC
                LIMIT %s
            """
            params.append(str(request.top_k * 2))

            results = []
            for row in CodeChunk.raw(sql, *params):
                results.append(
                    {
                        "chunk_id": row.id,
                        "score": float(row.rank),
                    }
                )
            return results

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
