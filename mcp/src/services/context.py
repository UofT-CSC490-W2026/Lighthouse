from ..types import (
    GetContextForChangeRequest,
    GetContextForChangeResponse,
)
from .mental_model import MentalModelService
from .ranking import RankingService
from .semantic_search import SemanticSearchService


class ContextService:
    """Placeholder service for top-level context retrieval orchestration."""

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
        candidates = await self.semantic_search_service.search_for_change(request)
        ranked = self.ranking_service.rank(candidates, limit=request.top_k)
        _ = await self.mental_model_service.get_module_signals(request.file)
        return GetContextForChangeResponse(items=ranked)
