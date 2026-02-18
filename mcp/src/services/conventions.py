"""Repository convention retrieval interfaces."""

from ..types import GetConventionsRequest, GetConventionsResponse


class ConventionService:
    """Return coding conventions inferred or configured for a repository."""

    async def get_conventions(
        self, request: GetConventionsRequest
    ) -> GetConventionsResponse:
        """Return convention entries relevant to the request scope."""
        _ = request
        return GetConventionsResponse(conventions=[])
