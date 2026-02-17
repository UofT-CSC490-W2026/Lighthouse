from fastapi import APIRouter

from ...types import GetDependencyContextRequest, GetDependencyContextResponse

router = APIRouter()


@router.post(
    "/get_dependency_context",
    response_model=GetDependencyContextResponse,
    summary="Stub tool: get dependency-specific context",
)
async def get_dependency_context(
    request: GetDependencyContextRequest,
) -> GetDependencyContextResponse:
    _ = request
    return GetDependencyContextResponse()

