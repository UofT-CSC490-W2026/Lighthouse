from fastapi import APIRouter

from .health import router as health_router
from .index_control import router as index_control_router

public_router = APIRouter()
public_router.include_router(health_router)
public_router.include_router(index_control_router)

__all__ = ["public_router"]
