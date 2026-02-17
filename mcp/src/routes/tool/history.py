from fastapi import APIRouter

from ...types import GetHistoryRequest, GetHistoryResponse

router = APIRouter()


@router.post(
    "/get_history",
    response_model=GetHistoryResponse,
    summary="Stub tool: get file history context",
)
async def get_history(request: GetHistoryRequest) -> GetHistoryResponse:
    _ = request
    return GetHistoryResponse(entries=[])

