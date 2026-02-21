"""Semantic retrieval service for MCP context queries."""

from __future__ import annotations

from ..types import GetContextForChangeRequest, MissingContextType, ToolContextItem
from .retrieval_backend import RetrievalBackendService


class SemanticSearchService:
    """Search runtime-indexed repository context and return ranked snippets."""

    def __init__(
        self,
        *,
        retrieval_backend: RetrievalBackendService,
    ) -> None:
        self.retrieval_backend = retrieval_backend

    async def search_for_change(
        self, request: GetContextForChangeRequest
    ) -> list[ToolContextItem]:
        """Return candidate context snippets relevant to a proposed change."""
        query_text = self._build_query_text(request)
        hits = await self.retrieval_backend.search(
            repo_id=request.repo_id,
            ref=request.ref,
            query_text=query_text,
            top_k=request.top_k,
            path_hint=request.file,
        )
        if not hits:
            return []

        items: list[ToolContextItem] = []
        for index, hit in enumerate(hits):
            score = _normalize_score(hit.score, rank=index, total=len(hits))
            items.append(
                ToolContextItem(
                    source_type=MissingContextType.rationale,
                    location=f"{hit.path}:{hit.start_char}-{hit.end_char}",
                    content=hit.text,
                    relevance_score=score,
                    explanation=(
                        "Retrieved semantically similar runtime-indexed chunk from "
                        f"{hit.path} (chunk {hit.chunk_index})."
                    ),
                )
            )
        return items

    def _build_query_text(self, request: GetContextForChangeRequest) -> str:
        """Construct one semantic query string from the tool request payload."""
        parts = [request.task_description.strip(), request.file.strip()]
        if request.function:
            parts.append(request.function.strip())
        return "\n".join(part for part in parts if part)


def _normalize_score(score: float, *, rank: int, total: int) -> float:
    """Normalize backend score into `[0, 1]` and apply small rank-based smoothing."""
    bounded = max(0.0, min(1.0, (score + 1.0) / 2.0))
    if total <= 1:
        return bounded
    rank_weight = max(0.0, 1.0 - (rank / max(1, total - 1)))
    blended = (bounded * 0.8) + (rank_weight * 0.2)
    return max(0.0, min(1.0, blended))
