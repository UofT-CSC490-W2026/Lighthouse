from ..types import (
    ContractRecord,
    GetCallersRequest,
    GetCallersResponse,
    GetContractRequest,
    GetContractResponse,
)


class CodeGraphService:
    """Placeholder service for code graph and contract queries."""

    async def get_callers(self, request: GetCallersRequest) -> GetCallersResponse:
        _ = request
        return GetCallersResponse(callers=[])

    async def get_contract(self, request: GetContractRequest) -> GetContractResponse:
        _ = request
        return GetContractResponse(contract=ContractRecord())

