"""Repository history service interfaces for MCP tool calls."""

from ..types import GetHistoryRequest, GetHistoryResponse


class HistoryService:
    """Serve repository history records (git, issues, PRs) for a query span."""

    async def get_history(self, request: GetHistoryRequest) -> GetHistoryResponse:
        """Return normalized history entries for the requested file or symbol span."""
        _ = request
        return GetHistoryResponse(entries=[])
