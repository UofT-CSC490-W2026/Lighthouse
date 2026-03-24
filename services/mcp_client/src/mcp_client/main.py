from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from logging import Logger

from db import DatabaseManager
from .utilities import Authenticator, DEBUG, get_logger, get_settings
from .engine import Engine
from .routers.http import HTTPRouteHandler
from .routers.mcp.handler import MCPToolHandler


class App(FastAPI):
    """FastAPI application wrapper that owns shared MCP service state."""

    log: Logger
    engine: Engine
    database: DatabaseManager
    authenticator: Authenticator

    def __init__(self):
        """Initialize settings, shared services, and middleware."""
        self.settings = get_settings()
        self.database = DatabaseManager(self.settings.postgres_dsn)
        super().__init__(
            debug=DEBUG,
            lifespan=self.lifespan,
        )

        self.log = get_logger(__name__)
        self.authenticator = Authenticator(self)
        self.engine = Engine(self)

        self.add_middleware(
            CORSMiddleware,
            allow_origins=self.settings.cors_allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @asynccontextmanager
    async def lifespan(self, *args, **kwargs):
        """Start routers, MCP state, and the database for the app lifespan."""
        http_handler = HTTPRouteHandler(self)
        mcp_handler = MCPToolHandler(self)
        started = False
        db_started = False
        try:
            self.log.info("Server startup: Initializing state")

            if self.database.is_configured:
                self.database.connect()
                db_started = True
                self.log.info("Database connection initialized")
            else:
                self.log.warning(
                    "POSTGRES_DSN is not configured; database startup skipped"
                )

            self.include_router(http_handler.as_router())
            self.mount("/mcp", mcp_handler)

            await mcp_handler.startup()
            started = True
            yield
        except Exception as e:
            self.log.error("Server startup failed: %s", e)
            raise RuntimeError(f"Failed to initialize server state: {e}")
        finally:
            if started:
                await mcp_handler.shutdown()
            if db_started:
                self.database.close()
                self.log.info("Database connection closed")
            self.log.info("Server shutdown")


app = App()
