from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import cast

from db import Chunk, DatabaseManager, IndexedFile, Repository, WikiPage
from embedding import EmbeddingProvider
from llm import LLMProvider
from shared.schemas.search import (
    CombinedSearchResult,
    CombinedSnippet,
    SearchContextSource,
    SearchRequest,
)
from vectordb import MilvusClient

from search.reranker.base_reranker import BaseReranker

from .search_strategy import SearchStrategy

logger = logging.getLogger(__name__)

KEYWORD_SYSTEM_PROMPT = (
    "You are a search keyword generator. Given a user's search query about a software project, "
    "extract 3 to 5 precise search keywords or short phrases that would be effective for "
    "full-text search across code and documentation. Return JSON: {\"keywords\": [\"kw1\", \"kw2\", ...]}"
)

VECTOR_OVERFETCH_MULTIPLIER = 4
MAX_VECTOR_OVERFETCH = 200
ACTIVE_PUBLISH_LOOKUP_BATCH_SIZE = 500


class LLMCombinedSearchStrategy(SearchStrategy[SearchRequest, CombinedSearchResult]):
    """Search strategy combining LLM keyword generation, vector + FTS across code and wiki, RRF fusion, and reranking."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        milvus_code: MilvusClient,
        milvus_wiki: MilvusClient,
        embedder: EmbeddingProvider,
        llm: LLMProvider,
        reranker: BaseReranker,
        llm_reasoning_effort: str,
    ) -> None:
        self.db_manager = db_manager
        self.milvus_code = milvus_code
        self.milvus_wiki = milvus_wiki
        self.embedder = embedder
        self.llm = llm
        self.reranker = reranker
        self.llm_reasoning_effort = llm_reasoning_effort

    async def search(self, request: SearchRequest) -> CombinedSearchResult:
        repo_id = self._resolve_repo_id(request.github_repo_id)

        # Phase 1: LLM keywords + vector searches in parallel
        llm_task = asyncio.create_task(self._generate_keywords(request.query))
        code_vector_task = asyncio.create_task(
            self._code_vector_search(request.query, repo_id, request.branch, request.top_k)
        )
        wiki_vector_task = asyncio.create_task(
            self._wiki_vector_search(request.query, repo_id, request.branch, request.top_k)
        )

        llm_keywords, code_vector_results, wiki_vector_results = await asyncio.gather(
            llm_task, code_vector_task, wiki_vector_task
        )

        llm_query = " ".join(llm_keywords) if llm_keywords else request.query

        # Phase 2: keyword searches in parallel (original query + LLM keywords)
        code_kw_orig, wiki_kw_orig, code_kw_llm, wiki_kw_llm = await asyncio.gather(
            asyncio.to_thread(
                self._code_keyword_search, request.query, request.top_k, repo_id, request.branch
            ),
            asyncio.to_thread(
                self._wiki_keyword_search, request.query, request.top_k, repo_id, request.branch
            ),
            asyncio.to_thread(
                self._code_keyword_search, llm_query, request.top_k, repo_id, request.branch
            ),
            asyncio.to_thread(
                self._wiki_keyword_search, llm_query, request.top_k, repo_id, request.branch
            ),
        )

        # Phase 3: RRF fusion across all 6 ranked lists
        # Separate code and wiki results, then fuse within each domain first
        code_fused = self._rrf_fusion_multi(
            [code_vector_results, code_kw_orig, code_kw_llm], k=60
        )
        wiki_fused = self._rrf_fusion_multi(
            [wiki_vector_results, wiki_kw_orig, wiki_kw_llm], k=60
        )

        # Load snippets for top candidates
        rerank_pool_size = min(request.top_k * 3, 50)
        code_top_ids = [r["chunk_id"] for r in code_fused[:rerank_pool_size]]
        wiki_top_ids = [r["chunk_id"] for r in wiki_fused[:rerank_pool_size]]

        code_score_map = {r["chunk_id"]: r["score"] for r in code_fused}
        wiki_score_map = {r["chunk_id"]: r["score"] for r in wiki_fused}

        code_snippets = self._load_code_snippets(code_top_ids, code_score_map)
        wiki_snippets = self._load_wiki_snippets(wiki_top_ids, wiki_score_map)

        # Cross-domain RRF fusion
        all_snippets = self._rrf_fuse_combined(
            [code_snippets, wiki_snippets], k=60
        )

        # Phase 4: Cohere reranking
        candidates = all_snippets[:rerank_pool_size]
        reranked = await self._rerank(request.query, candidates, request.top_k)

        return CombinedSearchResult(
            snippets=reranked,
            query=request.query,
            total_results=len(all_snippets),
        )

    # ── LLM keyword generation ──────────────────────────────────────────

    async def _generate_keywords(self, query: str) -> list[str]:
        try:
            messages = [
                {"role": "system", "content": KEYWORD_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ]
            result = await asyncio.to_thread(
                self.llm.complete_json,
                messages,
                reasoning_effort=self.llm_reasoning_effort,
            )
            keywords = result.get("keywords", [])
            if isinstance(keywords, list) and keywords:
                return [str(kw) for kw in keywords]
        except Exception:
            logger.warning("LLM keyword generation failed, falling back to original query", exc_info=True)
        return []

    # ── Vector search ───────────────────────────────────────────────────

    async def _code_vector_search(
        self, query: str, repo_id: str | None, branch: str, top_k: int
    ) -> list[dict]:
        try:
            query_embedding = self.embedder.embed_single(query)
            filters: dict[str, str] = {}
            if repo_id:
                filters["repository_id"] = repo_id
            if branch:
                filters["branch"] = branch

            raw_results = [
                asdict(r)
                for r in self.milvus_code.search(
                    query_embedding=query_embedding,
                    top_k=min(top_k * VECTOR_OVERFETCH_MULTIPLIER, MAX_VECTOR_OVERFETCH),
                    filters=filters if filters else None,
                )
            ]
            return self._filter_vector_results(raw_results)
        except Exception:
            logger.exception("Code vector search failed")
            return []

    async def _wiki_vector_search(
        self, query: str, repo_id: str | None, branch: str, top_k: int
    ) -> list[dict]:
        try:
            query_embedding = self.embedder.embed_single(query)
            filters: dict[str, str] = {}
            if repo_id:
                filters["repository_id"] = repo_id
            if branch:
                filters["branch"] = branch

            return [
                asdict(r)
                for r in self.milvus_wiki.search(
                    query_embedding=query_embedding,
                    top_k=top_k * 2,
                    filters=filters if filters else None,
                )
            ]
        except Exception:
            logger.exception("Wiki vector search failed")
            return []

    # ── Keyword search (PostgreSQL FTS) ─────────────────────────────────

    def _code_keyword_search(
        self, query: str, top_k: int, repo_id: str | None, branch: str | None
    ) -> list[dict]:
        with self.db_manager.connection_context():
            conditions = [
                "to_tsvector('english', chunks.content) @@ plainto_tsquery('english', %s)"
            ]
            params: list[str] = [query, query]

            if repo_id:
                conditions.append("chunks.repository_id = %s")
                params.append(repo_id)
            if branch:
                conditions.append("chunks.branch = %s")
                params.append(branch)

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
            params.append(str(top_k * 2))

            results = []
            for row in Chunk.raw(sql, *params):
                results.append({"chunk_id": row.id, "score": float(row.rank)})
            return results

    def _wiki_keyword_search(
        self, query: str, top_k: int, repo_id: str | None, branch: str | None
    ) -> list[dict]:
        with self.db_manager.connection_context():
            conditions = [
                "to_tsvector('english', content) @@ plainto_tsquery('english', %s)"
            ]
            params: list[str] = [query, query]

            if repo_id:
                conditions.append("repository_id = %s")
                params.append(repo_id)
            if branch:
                conditions.append("branch = %s")
                params.append(branch)

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
            params.append(str(top_k * 2))

            results = []
            for row in WikiPage.raw(sql, *params):
                results.append({"chunk_id": row.id, "score": float(row.rank)})
            return results

    # ── RRF fusion ──────────────────────────────────────────────────────

    @staticmethod
    def _rrf_fusion_multi(
        ranked_lists: list[list[dict]],
        k: int = 60,
    ) -> list[dict]:
        """Reciprocal Rank Fusion across N ranked lists of dicts with 'chunk_id'."""
        scores: dict[str, float] = {}
        data: dict[str, dict] = {}

        for ranked in ranked_lists:
            for rank, result in enumerate(ranked):
                cid = result["chunk_id"]
                scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
                if cid not in data:
                    data[cid] = result

        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
        return [{**data[cid], "score": scores[cid]} for cid in sorted_ids]

    @staticmethod
    def _rrf_fuse_combined(
        ranked_lists: list[list[CombinedSnippet]],
        k: int = 60,
    ) -> list[CombinedSnippet]:
        """RRF fusion across lists of CombinedSnippet objects."""
        scores: dict[str, float] = {}
        snippet_map: dict[str, CombinedSnippet] = {}

        for ranked in ranked_lists:
            for rank, snippet in enumerate(ranked):
                key = _combined_snippet_key(snippet)
                scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
                snippet_map.setdefault(key, snippet)

        return [
            snippet_map[key].model_copy(update={"score": scores[key]})
            for key in sorted(scores, key=lambda item: scores[item], reverse=True)
        ]

    # ── Snippet loading ─────────────────────────────────────────────────

    def _load_code_snippets(
        self, chunk_ids: list[str], score_map: dict[str, float]
    ) -> list[CombinedSnippet]:
        if not chunk_ids:
            return []

        with self.db_manager.connection_context():
            chunks = Chunk.select().where(Chunk.id.in_(chunk_ids))
            chunk_map = {c.id: c for c in chunks}

        snippets: list[CombinedSnippet] = []
        for chunk_id in chunk_ids:
            chunk = chunk_map.get(chunk_id)
            if chunk is None:
                continue
            snippets.append(
                CombinedSnippet(
                    context_source=SearchContextSource.code,
                    content=chunk.content,
                    score=score_map.get(chunk_id, 0.0),
                    file_path=chunk.file_path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                )
            )
        return snippets

    def _load_wiki_snippets(
        self, page_ids: list[str], score_map: dict[str, float]
    ) -> list[CombinedSnippet]:
        if not page_ids:
            return []

        with self.db_manager.connection_context():
            pages = WikiPage.select().where(WikiPage.id.in_(page_ids))
            page_map = {p.id: p for p in pages}

        snippets: list[CombinedSnippet] = []
        for page_id in page_ids:
            page = page_map.get(page_id)
            if page is None:
                continue
            snippets.append(
                CombinedSnippet(
                    context_source=SearchContextSource.wiki,
                    content=page.content,
                    score=score_map.get(page_id, 0.0),
                    page_title=page.title,
                    slug=page.slug,
                    section_path=page.section_path,
                )
            )
        return snippets

    # ── Reranking ───────────────────────────────────────────────────────

    async def _rerank(
        self,
        query: str,
        candidates: list[CombinedSnippet],
        top_n: int,
    ) -> list[CombinedSnippet]:
        if not candidates:
            return []
        try:
            documents = [s.content for s in candidates]
            ranked = await self.reranker.rerank(
                query=query, documents=documents, top_n=top_n
            )
            return [
                candidates[r.index].model_copy(update={"score": r.relevance_score})
                for r in ranked
            ]
        except Exception:
            logger.warning("Reranker failed, returning RRF-fused results", exc_info=True)
            return candidates[:top_n]

    # ── Helpers ─────────────────────────────────────────────────────────

    def _resolve_repo_id(self, github_repo_id: int) -> str | None:
        with self.db_manager.connection_context():
            repo = Repository.get_or_none(
                Repository.github_repo_id == github_repo_id
            )
            return repo.id if repo else None

    def _filter_vector_results(self, vector_results: list[dict]) -> list[dict]:
        if not vector_results:
            return []

        unique_file_keys = list(
            {
                cast(tuple[str, str, str], (r["repository_id"], r["branch"], r["file_path"]))
                for r in vector_results
            }
        )
        active_publish_by_file = self._get_active_publish_map(unique_file_keys)

        filtered = []
        for result in vector_results:
            publish_id = cast(str, result.get("publish_id", "legacy"))
            key = cast(
                tuple[str, str, str],
                (result["repository_id"], result["branch"], result["file_path"]),
            )
            if key not in active_publish_by_file:
                if publish_id == "legacy":
                    filtered.append(result)
                continue

            active_publish_id = active_publish_by_file[key]
            if active_publish_id is not None and publish_id == active_publish_id:
                filtered.append(result)

        return filtered

    def _get_active_publish_map(
        self, file_keys: list[tuple[str, str, str]]
    ) -> dict[tuple[str, str, str], str | None]:
        if not file_keys:
            return {}

        grouped: dict[tuple[str, str], set[str]] = {}
        for repository_id, branch, file_path in file_keys:
            grouped.setdefault((repository_id, branch), set()).add(file_path)

        active_publish: dict[tuple[str, str, str], str | None] = {}
        with self.db_manager.connection_context():
            for (repository_id, branch), file_paths in grouped.items():
                sorted_paths = sorted(file_paths)
                for i in range(0, len(sorted_paths), ACTIVE_PUBLISH_LOOKUP_BATCH_SIZE):
                    batch_paths = sorted_paths[i : i + ACTIVE_PUBLISH_LOOKUP_BATCH_SIZE]
                    rows = (
                        IndexedFile.select(
                            IndexedFile.repository,
                            IndexedFile.branch_name,
                            IndexedFile.file_path,
                            IndexedFile.active_publish_id,
                        )
                        .where(
                            (IndexedFile.repository == repository_id)
                            & (IndexedFile.branch_name == branch)
                            & (IndexedFile.file_path.in_(batch_paths))
                        )
                    )
                    if hasattr(rows, "tuples"):
                        rows = rows.tuples()
                    for row in rows:
                        if isinstance(row, tuple):
                            active_publish[(row[0], row[1], row[2])] = row[3]
                        else:
                            active_publish[
                                (row.repository_id, row.branch_name, row.file_path)
                            ] = row.active_publish_id

        return active_publish


def _combined_snippet_key(snippet: CombinedSnippet) -> str:
    if snippet.context_source is SearchContextSource.code:
        return (
            f"code:{snippet.file_path or ''}:"
            f"{snippet.start_line or 0}:{snippet.end_line or 0}"
        )
    return (
        f"wiki:{snippet.slug or ''}:"
        f"{snippet.section_path or ''}:{snippet.page_title or ''}"
    )
