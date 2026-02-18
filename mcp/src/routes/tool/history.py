"""Tool endpoint for repository history queries."""

from fastapi import APIRouter

from ...services import history_service
from ...types import GetHistoryRequest, GetHistoryResponse

router = APIRouter()


@router.post(
    "/get_history",
    response_model=GetHistoryResponse,
    summary="Stub tool: get file history context",
)
async def get_history(request: GetHistoryRequest) -> GetHistoryResponse:
    """Return history entries matching the request scope."""
    return await history_service.get_history(request)
