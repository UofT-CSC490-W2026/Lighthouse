from __future__ import annotations

import asyncio
import inspect
import typing
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request

from ...utilities import BoundRoute, RequestError, collect_routables
from ...utilities.logging import Colour, pp

if TYPE_CHECKING:
    from ...main import App


class HTTPRouteHandler:
    """Discover decorated HTTP handlers and register them on an APIRouter."""

    def __init__(self, app: App) -> None:
        """Create the router and register all engine-backed HTTP routes."""
        self.app = app
        self.router = APIRouter()
        self._register_routes()

    def as_router(self) -> APIRouter:
        """Expose the generated APIRouter instance."""
        return self.router

    def _register_routes(self) -> None:
        """Collect and register all decorated HTTP routes from the engine."""
        routes = collect_routables(*self.app.engine.registries())
        for bound in routes.values():
            self.router.add_api_route(
                path=bound.meta.path,
                endpoint=self.make_route_fn(bound),
                methods=[bound.meta.method],
                name=bound.meta.name or None,
                description=bound.meta.description or None,
            )
        self.log_routes(routes)

    @staticmethod
    def log_routes(routes: dict[str, BoundRoute]) -> None:
        """Pretty-print the discovered HTTP route table for startup visibility."""
        col_method = 8
        col_auth = 6
        col_path = 28
        col_desc = 48
        header = (
            f"  {'Method':<{col_method}}  "
            f"{'Auth':<{col_auth}}  "
            f"{'Path':<{col_path}}  "
            f"{'Description':<{col_desc}}  Owner"
        )
        divider = "  " + "-" * (len(header) - 2)

        pp(f"\nHTTP routes ({len(routes)} registered)\n", Colour.cyan)
        pp(header + "\n", Colour.bold_white)
        pp(divider + "\n", Colour.dim_grey)

        for bound in sorted(
            routes.values(),
            key=lambda route: (
                route.meta.path,
                route.meta.method,
                type(route.owner).__name__,
            ),
        ):
            owner = type(bound.owner).__name__
            desc = bound.meta.description or ""
            pp(f"  {bound.meta.method:<{col_method}}  ", Colour.bold_green)
            pp(
                f"{('yes' if bound.meta.auth_required else 'no'):<{col_auth}}  ",
                Colour.reset,
            )
            pp(f"{bound.meta.path:<{col_path}}  ", Colour.reset)
            pp(f"{desc:<{col_desc}}  ", Colour.reset)
            pp(owner + "\n", Colour.dim_grey)

        pp("\n")

    def make_route_fn(self, bound: BoundRoute):
        """Build a FastAPI endpoint wrapper around a bound engine method."""
        method = bound.method
        meta = bound.meta

        fn = getattr(method, "__func__", method)
        try:
            resolved_hints = typing.get_type_hints(fn, include_extras=True)
        except Exception:
            resolved_hints = {}

        orig_sig = inspect.signature(method)
        expects_request = "request" in orig_sig.parameters
        expects_auth = "auth" in orig_sig.parameters
        new_params = []
        if meta.auth_required and not expects_request:
            new_params.append(
                inspect.Parameter(
                    "request",
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=Request,
                )
            )
        for name, param in orig_sig.parameters.items():
            if name in ("self", "cls", "auth"):
                continue
            resolved_annotation = resolved_hints.get(name, param.annotation)
            new_params.append(param.replace(annotation=resolved_annotation))

        return_annotation = resolved_hints.get("return", orig_sig.return_annotation)
        new_sig = orig_sig.replace(
            parameters=new_params,
            return_annotation=return_annotation,
        )

        async def route_fn(*args, **kwargs):
            """Authenticate, invoke, and normalize errors for one HTTP route call."""
            call_kwargs = dict(kwargs)

            if meta.auth_required:
                request = call_kwargs.get("request")
                if request is None:
                    raise RuntimeError(
                        "Authenticated HTTP routes require a Request object."
                    )
                try:
                    auth = await self.app.authenticator.require_http_request(request)
                except RequestError as exc:
                    raise HTTPException(
                        status_code=exc.status_code, detail=exc.detail
                    ) from exc
                request.state.authenticated_user = auth
                if expects_auth:
                    call_kwargs["auth"] = auth

            if not expects_request:
                call_kwargs.pop("request", None)

            try:
                result = method(**call_kwargs)
            except RequestError as exc:
                raise HTTPException(
                    status_code=exc.status_code, detail=exc.detail
                ) from exc
            if asyncio.iscoroutine(result):
                try:
                    result = await result
                except RequestError as exc:
                    raise HTTPException(
                        status_code=exc.status_code, detail=exc.detail
                    ) from exc
            return result

        route_fn.__name__ = meta.name or getattr(method, "__name__", "route_fn")
        route_fn.__doc__ = meta.description or (method.__doc__ or "")
        route_fn.__signature__ = new_sig
        return route_fn


def build_router(*objects: Any) -> APIRouter:
    """Build an APIRouter from unprotected decorated routes only."""
    router = APIRouter()
    routes = collect_routables(*objects)
    for bound in routes.values():
        if bound.meta.auth_required:
            raise RuntimeError(
                "build_router(...) cannot build auth-protected routes without an App-bound HTTPRouteHandler."
            )
        router.add_api_route(
            path=bound.meta.path,
            endpoint=_make_route_fn(bound),
            methods=[bound.meta.method],
            name=bound.meta.name or None,
            description=bound.meta.description or None,
        )
    HTTPRouteHandler.log_routes(routes)
    return router


def _make_route_fn(bound: BoundRoute):
    """Build a simple route wrapper for legacy, non-auth router construction."""
    method = bound.method
    meta = bound.meta

    fn = getattr(method, "__func__", method)
    try:
        resolved_hints = typing.get_type_hints(fn, include_extras=True)
    except Exception:
        resolved_hints = {}

    orig_sig = inspect.signature(method)
    new_params = []
    for name, param in orig_sig.parameters.items():
        if name in ("self", "cls", "auth"):
            continue
        resolved_annotation = resolved_hints.get(name, param.annotation)
        new_params.append(param.replace(annotation=resolved_annotation))

    return_annotation = resolved_hints.get("return", orig_sig.return_annotation)
    new_sig = orig_sig.replace(
        parameters=new_params,
        return_annotation=return_annotation,
    )

    async def route_fn(*args, **kwargs):
        """Invoke a bound method without auth injection or request state handling."""
        result = method(**kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    route_fn.__name__ = meta.name or getattr(method, "__name__", "route_fn")
    route_fn.__doc__ = meta.description or (method.__doc__ or "")
    route_fn.__signature__ = new_sig
    return route_fn
