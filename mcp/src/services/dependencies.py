from ..types import GetDependencyContextRequest, GetDependencyContextResponse


class DependencyService:
    """Placeholder service for dependency context lookups."""

    async def get_dependency_context(
        self, request: GetDependencyContextRequest
    ) -> GetDependencyContextResponse:
        _ = request
        return GetDependencyContextResponse()
