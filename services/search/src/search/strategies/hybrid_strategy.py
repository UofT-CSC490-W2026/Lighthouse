from __future__ import annotations

import logging
from dataclasses import asdict
from typing import cast

from db import Chunk, DatabaseManager, IndexedFile, Repository
from embedding import EmbeddingProvider
from shared.schemas.search import CodeSnippet, SearchRequest, SearchResult
from vectordb import MilvusClient

from .search_strategy import SearchStrategy

logger = logging.getLogger(__name__)


class BranchNotIndexedError(RuntimeError):
    """Raised when a requested branch is not indexed for a repository."""


class HybridSearchStrategy(SearchStrategy[SearchRequest, SearchResult]):
    """Hybrid search combining vector similarity and PostgreSQL full-text search."""

    VECTOR_OVERFETCH_MULTIPLIER = 4
    MAX_VECTOR_OVERFETCH = 200
    ACTIVE_PUBLISH_LOOKUP_BATCH_SIZE = 500

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
                if not self._is_branch_indexed(repo.id, request.branch):
                    raise BranchNotIndexedError(
                        f"Branch requested not indexed or does not exist: \"{request.branch}\""
                    )

        attempt = self._search_for_branch(
            request=request,
            repo_id=repo_id,
            branch=request.branch,
        )
        logger.info(
            "Search attempt repo=%s github_repo_id=%s branch=%s vector=%d keyword=%d fused=%d snippets=%d keyword_mode=%s",
            repo_id,
            request.github_repo_id,
            request.branch,
            attempt["vector_count"],
            attempt["keyword_count"],
            attempt["fused_count"],
            len(attempt["snippets"]),
            attempt["keyword_mode"],
        )
        return SearchResult(
            snippets=attempt["snippets"],
            query=request.query,
            total_results=attempt["fused_count"],
        )

    def _keyword_search(
        self,
        query: str,
        top_k: int,
        repo_id: str | None,
        branch: str | None,
    ) -> tuple[list[dict], str]:
        """Execute PostgreSQL full-text search on chunks.content."""
        with self.db_manager.connection_context():
            # Build raw SQL for full-text search (Peewee's ORM doesn't
            # handle tsvector/tsquery parameterization cleanly)
            conditions = [
                "to_tsvector('english', chunks.content) @@ plainto_tsquery('english', %s)"
            ]
            params: list[str] = [query, query]  # one for WHERE, one for ts_rank

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
                results.append(
                    {
                        "chunk_id": row.id,
                        "score": float(row.rank),
                    }
                )
            if results:
                return results, "fts"

        # ILIKE lexical fallback intentionally disabled for now.
        return [], "none"

    # def _keyword_search_lexical(
    #     self,
    #     query: str,
    #     top_k: int,
    #     repo_id: str | None,
    #     branch: str | None,
    # ) -> list[dict]:
    #     """Fallback keyword search using ILIKE tokens when FTS has no matches."""
    #     terms = self._extract_terms(query)
    #     if not terms:
    #         return []
    #
    #     like_values = [f"%{term}%" for term in terms]
    #     score_expr = " + ".join(
    #         "(CASE WHEN content ILIKE %s THEN 1 ELSE 0 END)" for _ in like_values
    #     )
    #     like_expr = " OR ".join("content ILIKE %s" for _ in like_values)
    #
    #     conditions: list[str] = [f"({like_expr})"]
    #     condition_params: list[str] = [*like_values]
    #     if repo_id:
    #         conditions.append("repository_id = %s")
    #         condition_params.append(repo_id)
    #     if branch:
    #         conditions.append("branch = %s")
    #         condition_params.append(branch)
    #
    #     sql = f"""
    #         SELECT id, file_path, ({score_expr})::float AS rank
    #         FROM chunks
    #         WHERE {" AND ".join(conditions)}
    #         ORDER BY rank DESC
    #         LIMIT %s
    #     """
    #     params = [*like_values, *condition_params, str(top_k * 2)]
    #
    #     with self.db_manager.connection_context():
    #         results: list[dict] = []
    #         for row in Chunk.raw(sql, *params):
    #             results.append(
    #                 {
    #                     "chunk_id": row.id,
    #                     "score": float(row.rank),
    #                 }
    #             )
    #         return results

    def _search_for_branch(
        self,
        request: SearchRequest,
        repo_id: str | None,
        branch: str | None,
    ) -> dict:
        filters: dict[str, str] = {}
        if repo_id:
            filters["repository_id"] = repo_id
        if branch:
            filters["branch"] = branch

        vector_results: list[dict] = []
        try:
            query_embedding = self.embedder.embed_single(request.query)
            raw_vector_results = [
                asdict(r)
                for r in self.milvus.search(
                    query_embedding=query_embedding,
                    # Over-fetch because stale-publish hits may be filtered out
                    # before fusion.
                    top_k=min(
                        request.top_k * self.VECTOR_OVERFETCH_MULTIPLIER,
                        self.MAX_VECTOR_OVERFETCH,
                    ),
                    filters=filters if filters else None,
                )
            ]
            vector_results = self._filter_vector_results(raw_vector_results)
        except Exception:
            logger.exception("Vector search failed, falling back to keyword-only")

        keyword_search_result = self._keyword_search(
            query=request.query,
            top_k=request.top_k,
            repo_id=repo_id,
            branch=branch,
        )
        if isinstance(keyword_search_result, tuple):
            keyword_results, keyword_mode = keyword_search_result
        else:
            # Backward-compatible path for older tests/mocks returning only results.
            keyword_results = keyword_search_result
            keyword_mode = "fts" if keyword_results else "none"
        fused = self._rrf_fusion(vector_results, keyword_results, k=60)
        top_chunk_ids = [r["chunk_id"] for r in fused[: request.top_k]]
        snippets = self._load_snippets(top_chunk_ids, fused)

        return {
            "branch": branch,
            "keyword_mode": keyword_mode,
            "vector_count": len(vector_results),
            "keyword_count": len(keyword_results),
            "fused_count": len(fused),
            "snippets": snippets,
        }

    def _load_snippets(self, chunk_ids: list[str], fused: list[dict]) -> list[CodeSnippet]:
        if not chunk_ids:
            return []

        with self.db_manager.connection_context():
            chunks = Chunk.select().where(Chunk.id.in_(chunk_ids))  # type: ignore[arg-type]
            chunk_map = {c.id: c for c in chunks}

        # Build ordered snippets matching fusion order
        score_map = {row["chunk_id"]: row["score"] for row in fused}
        snippets: list[CodeSnippet] = []
        for chunk_id in chunk_ids:
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
        return snippets

    def _is_branch_indexed(self, repo_id: str, branch: str) -> bool:
        requested_branch = branch.strip()
        if not requested_branch:
            return False
        with self.db_manager.connection_context():
            repo_has_any_indexed_data = (
                Chunk.select()
                .where(Chunk.repository == repo_id)
                .limit(1)
                .exists()
                or IndexedFile.select()
                .where(IndexedFile.repository == repo_id)
                .limit(1)
                .exists()
            )
            if not repo_has_any_indexed_data:
                return True

            return (
                Chunk.select()
                .where(
                    (Chunk.repository == repo_id)
                    & (Chunk.branch == requested_branch)
                )
                .limit(1)
                .exists()
                or IndexedFile.select()
                .where(
                    (IndexedFile.repository == repo_id)
                    & (IndexedFile.branch_name == requested_branch)
                )
                .limit(1)
                .exists()
            )

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
            if active_publish_id is None:
                continue

            if publish_id == active_publish_id:
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
                for i in range(0, len(sorted_paths), self.ACTIVE_PUBLISH_LOOKUP_BATCH_SIZE):
                    batch_paths = sorted_paths[i : i + self.ACTIVE_PUBLISH_LOOKUP_BATCH_SIZE]
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
