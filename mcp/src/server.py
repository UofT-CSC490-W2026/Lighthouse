"""FastAPI application entrypoint for the MCP service."""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi_mcp import FastApiMCP
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .errors import MCPServiceError
from .utils import settings, get_logger
from .routes import Router


log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize application state and handle startup/shutdown logging."""
    try:
        log.info("Server startup: initializing state")
        app.state.settings = settings

        yield
    except Exception as e:
        log.error("Server startup failed: %s", e)
        raise RuntimeError(f"Failed to initialize server state: {e}")
    finally:
        log.info("Server shutdown")


app = FastAPI(
    title=settings.service_name,
    debug=settings.debug,
    lifespan=lifespan,
)


def _error_payload(*, code: str, message: str, details: object | None = None) -> dict:
    """Build the canonical JSON error envelope for MCP API responses."""
    payload = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if details is not None:
        payload["error"]["details"] = details
    return payload


@app.exception_handler(MCPServiceError)
async def _handle_mcp_service_error(
    _request: Request,
    exc: MCPServiceError,
) -> JSONResponse:
    """Map application-domain errors to canonical JSON error responses."""
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(
            code=exc.code,
            message=exc.message,
            details=exc.details,
        ),
    )


@app.exception_handler(RequestValidationError)
async def _handle_request_validation_error(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Normalize FastAPI request validation failures into MCP error shape."""
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            code="REQUEST_VALIDATION_ERROR",
            message="Invalid request payload",
            details=exc.errors(),
        ),
    )


@app.exception_handler(StarletteHTTPException)
async def _handle_http_exception(
    _request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Normalize fallback HTTP exceptions into MCP error shape."""
    detail = exc.detail
    message = detail if isinstance(detail, str) else "HTTP error"
    details = detail if not isinstance(detail, str) else None
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(
            code=f"HTTP_{exc.status_code}",
            message=message,
            details=details,
        ),
    )

if settings.debug:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

Router().attach(app)

mcp = FastApiMCP(app)
mcp.mount_http()
mcp.mount_sse()
