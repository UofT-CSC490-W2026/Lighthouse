"""Context orchestration service for MCP tool requests.

This service defines the high-level context retrieval contract:
1) collect candidate context snippets, 2) rank them, and
3) optionally enrich with mental-model signals.
"""

from ..types import (
    GetContextForChangeRequest,
    GetContextForChangeResponse,
)
from .mental_model import MentalModelService
from .ranking import RankingService
from .semantic_search import SemanticSearchService


class ContextService:
    """Coordinate context retrieval across search, ranking, and enrichment services."""

    def __init__(
        self,
        semantic_search_service: SemanticSearchService,
        ranking_service: RankingService,
        mental_model_service: MentalModelService,
    ):
        self.semantic_search_service = semantic_search_service
        self.ranking_service = ranking_service
        self.mental_model_service = mental_model_service

    async def get_context_for_change(
        self, request: GetContextForChangeRequest
    ) -> GetContextForChangeResponse:
        """Return ranked context items relevant to a proposed repository change.

        The response shape is canonical for `tools/get_context_for_change`.
        """
        candidates = await self.semantic_search_service.search_for_change(request)
        ranked = self.ranking_service.rank(candidates, limit=request.top_k)
        _ = await self.mental_model_service.get_module_signals(request.file)
        return GetContextForChangeResponse(items=ranked)
