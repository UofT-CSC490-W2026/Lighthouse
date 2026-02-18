"""Tool endpoint for repository history queries."""

from fastapi import APIRouter

from ...services import history_service
from ...types import GetHistoryRequest, GetHistoryResponse, ToolResponseEnvelope
from .common import build_tool_envelope, gate_tool_request

router = APIRouter()


@router.post(
    "/get_history",
    response_model=ToolResponseEnvelope[GetHistoryResponse],
    summary="Stub tool: get file history context",
)
async def get_history(
    tool_request: GetHistoryRequest,
) -> ToolResponseEnvelope[GetHistoryResponse]:
    """Return history entries matching the request scope."""
    gate = await gate_tool_request(
        repo_id=tool_request.repo_id,
        ref=tool_request.ref,
        tool_name="get_history",
    )
    if not gate.allow_execute:
        return build_tool_envelope(
            index=gate.index,
            message=gate.message,
            retry=gate.retry,
        )

    result = await history_service.get_history(tool_request)
    return build_tool_envelope(
        index=gate.index,
        result=result,
        message=gate.message,
    )
