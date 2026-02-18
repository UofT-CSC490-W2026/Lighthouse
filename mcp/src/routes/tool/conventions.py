"""Tool endpoint for repository convention lookups."""

from fastapi import APIRouter

from ...services import convention_service
from ...types import (
    GetConventionsRequest,
    GetConventionsResponse,
    ToolResponseEnvelope,
)
from .common import build_tool_envelope, gate_tool_request

router = APIRouter()


@router.post(
    "/get_conventions",
    response_model=ToolResponseEnvelope[GetConventionsResponse],
    summary="Stub tool: get repository conventions",
)
async def get_conventions(
    request: GetConventionsRequest,
) -> ToolResponseEnvelope[GetConventionsResponse]:
    """Return convention entries for the requested category/scope."""
    gate = await gate_tool_request(
        repo_id=request.repo_id,
        ref=request.ref,
        tool_name="get_conventions",
    )
    if not gate.allow_execute:
        return build_tool_envelope(
            index=gate.index,
            message=gate.message,
            retry=gate.retry,
        )

    result = await convention_service.get_conventions(request)
    return build_tool_envelope(
        index=gate.index,
        result=result,
        message=gate.message,
    )
