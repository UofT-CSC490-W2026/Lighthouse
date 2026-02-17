from fastapi import APIRouter

from ...services import dependency_service
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
    return await dependency_service.get_dependency_context(request)
