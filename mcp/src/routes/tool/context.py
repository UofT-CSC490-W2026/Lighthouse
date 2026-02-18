"""Tool endpoint for top-level context retrieval."""

from fastapi import APIRouter

from ...services import context_service
from ...types import (
    GetContextForChangeRequest,
    GetContextForChangeResponse,
    ToolResponseEnvelope,
)
from .common import build_tool_envelope, gate_tool_request

router = APIRouter()


@router.post(
    "/get_context_for_change",
    response_model=ToolResponseEnvelope[GetContextForChangeResponse],
    summary="Stub tool: get context for a planned change",
)
async def get_context_for_change(
    request: GetContextForChangeRequest,
) -> ToolResponseEnvelope[GetContextForChangeResponse]:
    """Return ranked context items for a proposed code change."""
    gate = await gate_tool_request(
        repo_id=request.repo_id,
        ref=request.ref,
        tool_name="get_context_for_change",
    )
    if not gate.allow_execute:
        return build_tool_envelope(
            index=gate.index,
            message=gate.message,
            retry=gate.retry,
        )

    result = await context_service.get_context_for_change(request)
    return build_tool_envelope(
        index=gate.index,
        result=result,
        message=gate.message,
    )
