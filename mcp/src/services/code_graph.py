"""Code graph and contract-query service interfaces."""

from ..types import (
    ContractRecord,
    GetCallersRequest,
    GetCallersResponse,
    GetContractRequest,
    GetContractResponse,
)


class CodeGraphService:
    """Expose call-graph and API-contract lookups for tool handlers."""

    async def get_callers(self, request: GetCallersRequest) -> GetCallersResponse:
        """Return call sites for a symbol, scoped by repository/ref context."""
        _ = request
        return GetCallersResponse(callers=[])

    async def get_contract(self, request: GetContractRequest) -> GetContractResponse:
        """Return the contract record for a symbol, route, or module target."""
        _ = request
        return GetContractResponse(contract=ContractRecord())
