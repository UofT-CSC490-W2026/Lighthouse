"""ASGI entrypoint exposing health endpoints for the pipeline worker service."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import settings
from .observability import configure_logging, structured_event
from .worker import run_worker_service

LOGGER = logging.getLogger(__name__)


def _set_worker_error(app: FastAPI, error: str | None) -> None:
    """Persist the latest worker startup/runtime error on app state."""
    app.state.worker_error = error


def _on_worker_task_done(app: FastAPI, task: asyncio.Task[Any]) -> None:
    """Capture worker task completion and record terminal errors for readiness."""
    try:
        task.result()
        _set_worker_error(app, "worker task exited unexpectedly")
        LOGGER.error(structured_event("pipeline.server.worker.exited"))
    except asyncio.CancelledError:
        LOGGER.info(structured_event("pipeline.server.worker.cancelled"))
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        _set_worker_error(app, error_message)
        LOGGER.exception(
            structured_event(
                "pipeline.server.worker.failed",
                error=error_message,
            )
        )


def _worker_status(app: FastAPI) -> tuple[str, str | None]:
    """Return `(worker_status, error_message)` for readiness calculations."""
    if not settings.run_worker_on_startup:
        return "disabled", None

    task: asyncio.Task[Any] | None = getattr(app.state, "worker_task", None)
    error_message: str | None = getattr(app.state, "worker_error", None)
    if error_message:
        return "failed", error_message
    if task is None:
        return "not_started", "worker task is not initialized"
    if task.done():
        return "stopped", "worker task is not running"
    return "running", None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize logging and optionally run worker loops in background."""
    configure_logging(debug=settings.debug)
    app.state.worker_task = None
    app.state.worker_error = None

    if settings.run_worker_on_startup:
        worker_task = asyncio.create_task(
            run_worker_service(configure_log=False),
            name="pipeline-worker-service",
        )
        worker_task.add_done_callback(lambda task: _on_worker_task_done(app, task))
        app.state.worker_task = worker_task
        LOGGER.info(
            structured_event(
                "pipeline.server.worker.starting",
                run_worker_on_startup=True,
            )
        )
    else:
        LOGGER.info(
            structured_event(
                "pipeline.server.worker.disabled",
                run_worker_on_startup=False,
            )
        )

    try:
        yield
    finally:
        worker_task: asyncio.Task[Any] | None = getattr(app.state, "worker_task", None)
        if worker_task is not None and not worker_task.done():
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task


app = FastAPI(title="Lighthouse Pipeline Service", debug=settings.debug, lifespan=lifespan)


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Return liveness payload indicating process responsiveness."""
    worker_state, _ = _worker_status(request.app)
    return {
        "status": "ok",
        "service": "pipeline",
        "worker_status": worker_state,
    }


@app.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Return readiness based on worker runtime health and startup outcomes."""
    worker_state, error_message = _worker_status(request.app)
    is_ready = worker_state in {"running", "disabled"}
    payload = {
        "status": "ready" if is_ready else "not_ready",
        "service": "pipeline",
        "worker_status": worker_state,
    }
    if error_message:
        payload["error"] = error_message
    if is_ready:
        return JSONResponse(status_code=200, content=payload)
    return JSONResponse(status_code=503, content=payload)
