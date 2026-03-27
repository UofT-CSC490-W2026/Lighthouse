from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from mcp_server.routers.http.handler import HTTPRouteHandler, _make_route_fn, build_router
from mcp_server.routers.mcp.handler import MCPToolHandler
from mcp_server.utilities import RequestError, httproute, toolcall
from mcp_server.utilities.decorators import BoundRoute, BoundToolCall, RouteMeta, ToolCallMeta


class EchoModel(BaseModel):
    value: str


class DemoRoutes:
    @httproute("GET", "/public", name="public", auth_required=False)
    async def public(self, name: str) -> dict[str, str]:
        return {"name": name}

    @httproute("GET", "/private", name="private")
    async def private(self, auth, value: str) -> dict[str, str]:
        if value == "bad":
            raise RequestError("bad request", status_code=422)
        return {"value": value, "user": auth.id}


class DemoTools:
    @toolcall("echo")
    async def echo(self, auth, value: str) -> EchoModel:
        if value == "bad":
            raise RequestError("bad tool", status_code=422)
        return EchoModel(value=f"{auth.id}:{value}")

    @toolcall("list_echo", auth_required=False)
    async def list_echo(self, value: str) -> list[EchoModel]:
        return [EchoModel(value=value)]


class PublicRoutes:
    @httproute("GET", "/public-only", name="public_only", auth_required=False)
    async def public_only(self, name: str) -> dict[str, str]:
        return {"name": name}


class ForwardRefRoutes:
    @httproute("GET", "/forward", name="forward", auth_required=False)
    def forward(self, value: "MissingType") -> "MissingReturn":
        return {"value": value}


class CtxTools:
    @toolcall("ctx_echo")
    async def ctx_echo(self, ctx, auth, value: str) -> str:
        return f"{auth.id}:{value}:{bool(ctx)}"

    @toolcall("sync_fail", auth_required=False)
    def sync_fail(self, value: str) -> str:
        raise RequestError(f"bad:{value}", status_code=400)


class AuthParamPublic:
    @httproute("GET", "/auth-public", name="auth_public", auth_required=False)
    def auth_public(self, auth, value: str) -> dict[str, str]:
        return {"value": value}


class SyncErrorRoute:
    @httproute("GET", "/sync-http", name="sync_http")
    def sync_http(self, auth, value: str) -> dict[str, str]:
        raise RequestError("sync-http", status_code=409)


class ForwardTool:
    @toolcall("forward_tool", auth_required=False)
    def forward_tool(self, value: "MissingType") -> str:
        return value


@pytest.mark.unit
@pytest.mark.asyncio
async def test_http_route_handler_auth_and_error_paths(monkeypatch):
    app = SimpleNamespace(
        engine=SimpleNamespace(registries=lambda: (DemoRoutes(),)),
        authenticator=SimpleNamespace(
            require_http_request=AsyncMock(return_value=SimpleNamespace(id="user-1"))
        ),
    )
    handler = HTTPRouteHandler(app)

    route = next(route for route in handler.router.routes if route.name == "private")
    request = SimpleNamespace(state=SimpleNamespace())

    assert await route.endpoint(request=request, value="ok") == {"value": "ok", "user": "user-1"}

    with pytest.raises(Exception) as exc_info:
        await route.endpoint(request=request, value="bad")
    assert exc_info.value.status_code == 422

    app.authenticator.require_http_request = AsyncMock(
        side_effect=RequestError("denied", status_code=401)
    )
    with pytest.raises(Exception) as exc_info:
        await route.endpoint(request=request, value="ok")
    assert exc_info.value.status_code == 401


@pytest.mark.unit
@pytest.mark.asyncio
async def test_http_route_handler_requires_request_and_legacy_builder():
    app = SimpleNamespace(
        engine=SimpleNamespace(registries=lambda: ()),
        authenticator=SimpleNamespace(require_http_request=AsyncMock()),
    )
    bound = BoundRoute(
        meta=RouteMeta(method="GET", path="/x", name="x"),
        method=DemoRoutes().private,
        owner=DemoRoutes(),
    )
    route_fn = HTTPRouteHandler(app).make_route_fn(bound)

    with pytest.raises(RuntimeError, match="require a Request object"):
        await route_fn(value="ok")

    public_router = build_router(PublicRoutes())
    public_route = next(route for route in public_router.routes if route.name == "public_only")
    assert await public_route.endpoint(name="octo") == {"name": "octo"}
    assert inspect.signature(public_route.endpoint).parameters["name"].annotation is str

    with pytest.raises(RuntimeError, match="cannot build auth-protected routes"):
        build_router(DemoRoutes())

    bound = BoundRoute(
        meta=RouteMeta(method="GET", path="/auth-public", name="auth_public", auth_required=False),
        method=AuthParamPublic().auth_public,
        owner=AuthParamPublic(),
    )
    route_fn = _make_route_fn(bound)
    assert "auth" not in inspect.signature(route_fn).parameters


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_route_fn_handles_sync_request_errors():
    class SyncRoutes:
        @httproute("GET", "/sync", name="sync", auth_required=False)
        def sync(self, value: str) -> dict[str, str]:
            raise RequestError(f"bad:{value}", status_code=400)

    bound = BoundRoute(
        meta=RouteMeta(method="GET", path="/sync", name="sync", auth_required=False),
        method=SyncRoutes().sync,
        owner=SyncRoutes(),
    )
    route_fn = _make_route_fn(bound)
    with pytest.raises(RequestError):
        await route_fn(value="x")

    bound = BoundRoute(
        meta=RouteMeta(method="GET", path="/forward", name="forward", auth_required=False),
        method=ForwardRefRoutes().forward,
        owner=ForwardRefRoutes(),
    )
    route_fn = _make_route_fn(bound)
    assert "MissingType" in inspect.signature(route_fn).parameters["value"].annotation

    app = SimpleNamespace(
        engine=SimpleNamespace(registries=lambda: ()),
        authenticator=SimpleNamespace(require_http_request=AsyncMock(return_value=SimpleNamespace(id="user-1"))),
    )
    bound = BoundRoute(
        meta=RouteMeta(method="GET", path="/sync-http", name="sync_http", auth_required=True),
        method=SyncErrorRoute().sync_http,
        owner=SyncErrorRoute(),
    )
    route_fn = HTTPRouteHandler(app).make_route_fn(bound)
    with pytest.raises(Exception) as exc_info:
        await route_fn(request=SimpleNamespace(state=SimpleNamespace()), value="x")
    assert exc_info.value.status_code == 409

    app = SimpleNamespace(
        engine=SimpleNamespace(registries=lambda: ()),
        authenticator=SimpleNamespace(require_http_request=AsyncMock(return_value=SimpleNamespace(id="user-1"))),
    )
    bound = BoundRoute(
        meta=RouteMeta(method="GET", path="/forward-http", name="forward_http", auth_required=False),
        method=ForwardRefRoutes().forward,
        owner=ForwardRefRoutes(),
    )
    handler = HTTPRouteHandler(app)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("mcp_server.routers.http.handler.typing.get_type_hints", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
        route_fn = handler.make_route_fn(bound)
    assert "value" in inspect.signature(route_fn).parameters


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mcp_tool_handler_startup_shutdown_and_wrappers(monkeypatch):
    app = SimpleNamespace(
        engine=SimpleNamespace(registries=lambda: (DemoTools(),)),
        authenticator=SimpleNamespace(
            require_mcp_context=AsyncMock(return_value=SimpleNamespace(id="user-1"))
        ),
    )
    handler = MCPToolHandler(app)
    lifespan_ctx = SimpleNamespace(__aenter__=AsyncMock(), __aexit__=AsyncMock())
    handler._starlette_app = SimpleNamespace(
        lifespan=lambda _app: lifespan_ctx,
    )

    await handler.startup()
    await handler.startup()
    await handler.shutdown()
    await handler.shutdown()

    tool = BoundToolCall(
        meta=ToolCallMeta(name="echo"),
        method=DemoTools().echo,
        owner=DemoTools(),
    )
    tool_fn = handler._make_tool_fn(tool)
    result = await tool_fn(SimpleNamespace(), value="ok")
    assert result == {"value": "user-1:ok"}

    with pytest.raises(ValueError, match="bad tool"):
        await tool_fn(SimpleNamespace(), value="bad")

    app.authenticator.require_mcp_context = AsyncMock(
        side_effect=RequestError("forbidden", status_code=403)
    )
    with pytest.raises(PermissionError, match="forbidden"):
        await tool_fn(SimpleNamespace(), value="ok")
    app.authenticator.require_mcp_context = AsyncMock(
        return_value=SimpleNamespace(id="user-1")
    )

    list_tool = BoundToolCall(
        meta=ToolCallMeta(name="list_echo", auth_required=False),
        method=DemoTools().list_echo,
        owner=DemoTools(),
    )
    list_tool_fn = handler._make_tool_fn(list_tool)
    assert await list_tool_fn(SimpleNamespace(), value="x") == [{"value": "x"}]

    ctx_tool = BoundToolCall(
        meta=ToolCallMeta(name="ctx_echo"),
        method=CtxTools().ctx_echo,
        owner=CtxTools(),
    )
    ctx_tool_fn = handler._make_tool_fn(ctx_tool)
    assert await ctx_tool_fn(SimpleNamespace(), value="x") == "user-1:x:True"

    sync_fail_tool = BoundToolCall(
        meta=ToolCallMeta(name="sync_fail", auth_required=False),
        method=CtxTools().sync_fail,
        owner=CtxTools(),
    )
    sync_fail_tool_fn = handler._make_tool_fn(sync_fail_tool)
    with pytest.raises(ValueError, match="bad:x"):
        await sync_fail_tool_fn(SimpleNamespace(), value="x")

    forward_tool = BoundToolCall(
        meta=ToolCallMeta(name="forward_tool", auth_required=False),
        method=ForwardTool().forward_tool,
        owner=ForwardTool(),
    )
    forward_tool_fn = handler._make_tool_fn(forward_tool)
    assert "MissingType" in inspect.signature(forward_tool_fn).parameters["value"].annotation


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mcp_tool_handler_call_delegates_to_starlette_app():
    called = []

    async def fake_app(scope, receive, send):
        called.append((scope, receive, send))

    handler = MCPToolHandler(
        SimpleNamespace(
            engine=SimpleNamespace(registries=lambda: (DemoTools(),)),
            authenticator=SimpleNamespace(require_mcp_context=AsyncMock()),
        )
    )
    handler._starlette_app = fake_app

    await handler({}, object(), object())

    assert len(called) == 1
