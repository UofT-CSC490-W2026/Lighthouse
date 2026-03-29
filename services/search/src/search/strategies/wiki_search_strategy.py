from __future__ import annotations

import logging
from dataclasses import asdict

from db import DatabaseManager, Repository, WikiPage
from embedding import EmbeddingProvider
from shared.schemas.search import WikiSearchRequest, WikiSearchResult, WikiSnippet
from vectordb import MilvusClient

from .search_strategy import SearchStrategy

logger = logging.getLogger(__name__)


class HybridWikiSearchStrategy(SearchStrategy[WikiSearchRequest, WikiSearchResult]):
    """Hybrid search over generated wiki pages (vector + keyword)."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        milvus: MilvusClient,
        embedder: EmbeddingProvider,
    ) -> None:
        self.db_manager = db_manager
        self.milvus = milvus
        self.embedder = embedder

    async def search(self, request: WikiSearchRequest) -> WikiSearchResult:
        repo_id: str | None = None
        with self.db_manager.connection_context():
            repo = Repository.get_or_none(
                Repository.github_repo_id == request.github_repo_id
            )
            if repo:
                repo_id = repo.id

        filters: dict[str, str] = {}
        if repo_id:
            filters["repository_id"] = repo_id
        if request.branch:
            filters["branch"] = request.branch

        # 1. Vector search over wiki_embeddings
        vector_results: list[dict] = []
        try:
            query_embedding = self.embedder.embed_single(request.query)
            vector_results = [
                asdict(r)
                for r in self.milvus.search(
                    query_embedding=query_embedding,
                    top_k=request.top_k * 2,
                    filters=filters if filters else None,
                )
            ]
        except Exception:
            logger.exception("Wiki vector search failed, falling back to keyword-only")

        # 2. Keyword search over wiki_pages
        keyword_results = self._keyword_search(request, repo_id)

        # 3. Reciprocal Rank Fusion
        fused = self._rrf_fusion(vector_results, keyword_results, k=60)

        # 4. Fetch top_k wiki pages
        top_page_ids = [r["chunk_id"] for r in fused[: request.top_k]]

        if not top_page_ids:
            return WikiSearchResult(snippets=[], query=request.query, total_results=0)

        with self.db_manager.connection_context():
            pages = WikiPage.select().where(WikiPage.id.in_(top_page_ids))
            page_map = {p.id: p for p in pages}

        score_map = {r["chunk_id"]: r["score"] for r in fused}
        snippets: list[WikiSnippet] = []
        for page_id in top_page_ids:
            page = page_map.get(page_id)
            if page is None:
                continue
            # Truncate content to a snippet
            content_snippet = page.content[:500] + "..." if len(page.content) > 500 else page.content
            snippets.append(
                WikiSnippet(
                    page_title=page.title,
                    slug=page.slug,
                    section_path=page.section_path,
                    content_snippet=content_snippet,
                    score=score_map.get(page_id, 0.0),
                )
            )

        return WikiSearchResult(
            snippets=snippets,
            query=request.query,
            total_results=len(fused),
        )

    def _keyword_search(
        self, request: WikiSearchRequest, repo_id: str | None
    ) -> list[dict]:
        """Execute PostgreSQL full-text search on wiki_pages.content."""
        with self.db_manager.connection_context():
            conditions = [
                "to_tsvector('english', content) @@ plainto_tsquery('english', %s)"
            ]
            params: list[str] = [request.query, request.query]

            if repo_id:
                conditions.append("repository_id = %s")
                params.append(repo_id)
            if request.branch:
                conditions.append("branch = %s")
                params.append(request.branch)

            where_clause = " AND ".join(conditions)
            sql = f"""
                SELECT id, slug,
                       ts_rank(to_tsvector('english', content),
                               plainto_tsquery('english', %s)) as rank
                FROM wiki_pages
                WHERE {where_clause}
                ORDER BY rank DESC
                LIMIT %s
            """
            params.append(str(request.top_k * 2))

            results = []
            for row in WikiPage.raw(sql, *params):
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
        data: dict[str, dict] = {}

        for rank, result in enumerate(vector_results):
            cid = result["chunk_id"]
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank + 1)
            data[cid] = result

        for rank, result in enumerate(keyword_results):
            cid = result["chunk_id"]
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank + 1)
            if cid not in data:
                data[cid] = result

        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        return [{**data[cid], "score": scores[cid]} for cid in sorted_ids]
