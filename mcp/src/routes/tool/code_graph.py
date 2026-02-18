"""Tool endpoints for code graph and contract lookups."""

from fastapi import APIRouter

from ...services import code_graph_service
from ...types import (
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
    """Return caller records for a requested symbol."""
    return await code_graph_service.get_callers(request)


@router.post(
    "/get_contract",
    response_model=GetContractResponse,
    summary="Stub tool: get contract for a symbol",
)
async def get_contract(request: GetContractRequest) -> GetContractResponse:
    """Return contract metadata for a requested symbol."""
    return await code_graph_service.get_contract(request)
