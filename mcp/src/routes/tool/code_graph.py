from fastapi import APIRouter

from ...types import (
    ContractRecord,
    GetCallersRequest,
    GetCallersResponse,
    GetContractRequest,
    GetContractResponse,
)

router = APIRouter()


@router.post(
    "/get_callers",
    response_model=GetCallersResponse,
    summary="Stub tool: get callers for a symbol",
)
async def get_callers(request: GetCallersRequest) -> GetCallersResponse:
    _ = request
    return GetCallersResponse(callers=[])


@router.post(
    "/get_contract",
    response_model=GetContractResponse,
    summary="Stub tool: get contract for a symbol",
)
async def get_contract(request: GetContractRequest) -> GetContractResponse:
    _ = request
    return GetContractResponse(contract=ContractRecord())

