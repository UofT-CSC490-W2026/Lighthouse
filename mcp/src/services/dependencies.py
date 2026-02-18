"""Dependency-context retrieval interfaces."""

from ..types import GetDependencyContextRequest, GetDependencyContextResponse


class DependencyService:
    """Provide dependency context for impacted files, symbols, or modules."""

    async def get_dependency_context(
        self, request: GetDependencyContextRequest
    ) -> GetDependencyContextResponse:
        """Return direct/transitive dependency records for the request target."""
        _ = request
        return GetDependencyContextResponse()
