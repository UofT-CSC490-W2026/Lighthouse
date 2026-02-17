from ..types import GetContextForChangeRequest, ToolContextItem


class SemanticSearchService:
    """Placeholder service for semantic retrieval over indexed context."""

    async def search_for_change(
        self, request: GetContextForChangeRequest
    ) -> list[ToolContextItem]:
        _ = request
        return []
