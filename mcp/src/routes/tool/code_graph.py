"""Tool endpoints for code graph and contract lookups."""

from fastapi import APIRouter, Request

from ...services import code_graph_service
from ...types import (
    GetCallersRequest,
    GetCallersResponse,
    GetContractRequest,
    GetContractResponse,
    ToolResponseEnvelope,
)
from .common import build_tool_envelope, gate_tool_request, resolve_request_github_token

router = APIRouter()


@router.post(
    "/get_callers",
    response_model=ToolResponseEnvelope[GetCallersResponse],
    summary="Stub tool: get callers for a symbol",
)
async def get_callers(
    http_request: Request,
    tool_request: GetCallersRequest,
) -> ToolResponseEnvelope[GetCallersResponse]:
    """Return caller records for a requested symbol."""
    gate = await gate_tool_request(
        repo_id=tool_request.repo_id,
        ref=tool_request.ref,
        tool_name="get_callers",
        github_token=resolve_request_github_token(http_request),
    )
    if not gate.allow_execute:
        return build_tool_envelope(
            index=gate.index,
            message=gate.message,
            retry=gate.retry,
        )

    result = await code_graph_service.get_callers(tool_request)
    return build_tool_envelope(
        index=gate.index,
        result=result,
        message=gate.message,
    )


@router.post(
    "/get_contract",
    response_model=ToolResponseEnvelope[GetContractResponse],
    summary="Stub tool: get contract for a symbol",
)
async def get_contract(
    http_request: Request,
    tool_request: GetContractRequest,
) -> ToolResponseEnvelope[GetContractResponse]:
    """Return contract metadata for a requested symbol."""
    gate = await gate_tool_request(
        repo_id=tool_request.repo_id,
        ref=tool_request.ref,
        tool_name="get_contract",
        github_token=resolve_request_github_token(http_request),
    )
    if not gate.allow_execute:
        return build_tool_envelope(
            index=gate.index,
            message=gate.message,
            retry=gate.retry,
        )

    result = await code_graph_service.get_contract(tool_request)
    return build_tool_envelope(
        index=gate.index,
        result=result,
        message=gate.message,
    )
