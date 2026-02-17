from ..types import GetHistoryRequest, GetHistoryResponse


class HistoryService:
    """Placeholder service for git/issue/PR history lookups."""

    async def get_history(self, request: GetHistoryRequest) -> GetHistoryResponse:
        _ = request
        return GetHistoryResponse(entries=[])
