from ..types import GetConventionsRequest, GetConventionsResponse


class ConventionService:
    """Placeholder service for repository convention queries."""

    async def get_conventions(
        self, request: GetConventionsRequest
    ) -> GetConventionsResponse:
        _ = request
        return GetConventionsResponse(conventions=[])
