from fastapi import APIRouter

from ...types import GetConventionsRequest, GetConventionsResponse

router = APIRouter()


@router.post(
    "/get_conventions",
    response_model=GetConventionsResponse,
    summary="Stub tool: get repository conventions",
)
async def get_conventions(request: GetConventionsRequest) -> GetConventionsResponse:
    _ = request
    return GetConventionsResponse(conventions=[])

