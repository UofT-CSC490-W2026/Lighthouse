"""Semantic retrieval interface for MCP context queries."""

from ..types import GetContextForChangeRequest, ToolContextItem


class SemanticSearchService:
    """Search indexed repository context and return candidate snippets."""

    async def search_for_change(
        self, request: GetContextForChangeRequest
    ) -> list[ToolContextItem]:
        """Return candidate context items for a proposed code change request."""
        _ = request
        return []
