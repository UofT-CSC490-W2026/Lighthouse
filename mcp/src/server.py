from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi_mcp import FastApiMCP
from fastapi.middleware.cors import CORSMiddleware

from .utils import settings, get_logger
from .routes import Router


log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
