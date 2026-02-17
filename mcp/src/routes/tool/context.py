from fastapi import APIRouter

from ...types import GetContextForChangeRequest, GetContextForChangeResponse

router = APIRouter()


@router.post(
    "/get_context_for_change",
    response_model=GetContextForChangeResponse,
    summary="Stub tool: get context for a planned change",
)
async def get_context_for_change(
    request: GetContextForChangeRequest,
) -> GetContextForChangeResponse:
    _ = request
    return GetContextForChangeResponse(items=[])

