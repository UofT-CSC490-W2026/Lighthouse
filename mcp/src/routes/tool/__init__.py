"""MCP tool endpoint route group."""

from fastapi import APIRouter

from .code_graph import router as code_graph_router
from .context import router as context_router
from .conventions import router as conventions_router
from .dependencies import router as dependencies_router
from .history import router as history_router

tool_router = APIRouter(prefix="/tools", tags=["tools"])
tool_router.include_router(context_router)
tool_router.include_router(code_graph_router)
tool_router.include_router(history_router)
tool_router.include_router(conventions_router)
tool_router.include_router(dependencies_router)

__all__ = ["tool_router"]
