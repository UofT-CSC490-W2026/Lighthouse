"""Tool endpoint for dependency context queries."""

from fastapi import APIRouter

from ...services import dependency_service
from ...types import (
    GetDependencyContextRequest,
    GetDependencyContextResponse,
    ToolResponseEnvelope,
)
from .common import build_tool_envelope, gate_tool_request

router = APIRouter()


@router.post(
    "/get_dependency_context",
    response_model=ToolResponseEnvelope[GetDependencyContextResponse],
    summary="Stub tool: get dependency-specific context",
)
async def get_dependency_context(
    tool_request: GetDependencyContextRequest,
) -> ToolResponseEnvelope[GetDependencyContextResponse]:
    """Return dependency context records for a package or API."""
    gate = await gate_tool_request(
        repo_id=tool_request.repo_id,
        ref=tool_request.ref,
        tool_name="get_dependency_context",
    )
    if not gate.allow_execute:
        return build_tool_envelope(
            index=gate.index,
            message=gate.message,
            retry=gate.retry,
        )

    result = await dependency_service.get_dependency_context(tool_request)
    return build_tool_envelope(
        index=gate.index,
        result=result,
        message=gate.message,
    )
