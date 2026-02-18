"""Tool endpoint for repository convention lookups."""

from fastapi import APIRouter

from ...services import convention_service
from ...types import GetConventionsRequest, GetConventionsResponse

router = APIRouter()


@router.post(
    "/get_conventions",
    response_model=GetConventionsResponse,
    summary="Stub tool: get repository conventions",
)
async def get_conventions(request: GetConventionsRequest) -> GetConventionsResponse:
    """Return convention entries for the requested category/scope."""
    return await convention_service.get_conventions(request)
