from __future__ import annotations

import asyncio
import inspect
import json
import logging
import typing
from typing import TYPE_CHECKING, Any

from fastmcp import Context, FastMCP

from ...utilities.decorators import BoundToolCall, collect_toolcalls, params_to_model
from ...utilities import RequestError, log_error, to_public_error

if TYPE_CHECKING:
    from ...main import App


def _safe_log(app: Any, exc: Exception, envelope) -> None:
    logger = getattr(app, "log", None)
    if logger is None:
        logger = logging.getLogger(__name__)
    log_error(logger, exc, envelope)


MCP_INSTRUCTIONS = """
Lighthouse is a retrieval-focused MCP server for coding agents.

Use this server when you need better context for a coding task than is available from the
current file or local workspace alone. The goal is to surface the broader understanding
needed to make correct changes, such as architectural decisions, important invariants,
cross-file relationships, repository conventions, and deeper codebase context.

The primary retrieval entrypoint is `search_code`.

When calling `search_code`, provide:
- the repository you are working in
- the search query or task you are trying to complete
- the branch you want to search
- an optional file path when you want to narrow the search to a specific file

Use Lighthouse to answer questions like:
- What context is missing for this change?
- What parts of the codebase or architecture matter for this task?
- Are there conventions, historical constraints, or non-local dependencies I should know?
- What additional files or code regions should I inspect before editing?

Prefer Lighthouse when the task likely depends on broader repository understanding rather
than only the code already visible in the editor.
""".strip()


class MCPToolHandler:
    """
    ASGI sub-application that exposes all @toolcall-decorated methods from the
    engine and registries as FastMCP tools, mounted at /mcp.

    Tool functions are generated dynamically at startup: their signatures are
    transplanted from the original methods so FastMCP can introspect them for
    JSON schema generation and argument parsing.
    """

    def __init__(self, app: App) -> None:
        """Create the FastMCP app and register decorated engine tools."""
        self.app = app
        self.mcp = FastMCP(
            "Lighthouse MCP Server",
            instructions=MCP_INSTRUCTIONS,
        )
        self._register_tools()
        # Build the Starlette sub-app once so the mounted MCP surface stays stable.
        self._starlette_app = self.mcp.http_app(
            path="/",
            transport="streamable-http",
            stateless_http=True,
        )
        self._lifespan_ctx: Any = None

    async def startup(self) -> None:
        """Enter the mounted FastMCP app lifespan so its task group is initialized."""
        if self._lifespan_ctx is not None:
            return
        self._lifespan_ctx = self._starlette_app.lifespan(self._starlette_app)
        await self._lifespan_ctx.__aenter__()

    async def shutdown(self) -> None:
        """Exit the mounted FastMCP app lifespan if it was started."""
        if self._lifespan_ctx is None:
            return
        await self._lifespan_ctx.__aexit__(None, None, None)
        self._lifespan_ctx = None

    def _register_tools(self) -> None:
        """Collect and register all decorated MCP tools from the engine."""
        tools = collect_toolcalls(
            *self.app.engine.registries(),
        )
        for bound in tools.values():
            self.mcp.tool()(self._make_tool_fn(bound))
        self._log_tools(tools)

    def _log_tools(self, tools: dict) -> None:
        """Pretty-print the discovered MCP tool table for startup visibility."""
        from ...utilities.logging import Colour, pp

        col_name = 28
        col_auth = 6
        col_desc = 48
        header = f"  {'Tool':<{col_name}}  {'Auth':<{col_auth}}  {'Description':<{col_desc}}  Owner"
        divider = "  " + "-" * (len(header) - 2)
        pp(f"\nMCP tools ({len(tools)} registered)\n", Colour.cyan)
        pp(header + "\n", Colour.bold_white)
        pp(divider + "\n", Colour.dim_grey)
        for name, bound in sorted(tools.items()):
            owner = type(bound.owner).__name__
            desc = bound.meta.description or ""
            pp(f"  {name:<{col_name}}  ", Colour.bold_green)
            pp(
                f"{('yes' if bound.meta.auth_required else 'no'):<{col_auth}}  ",
                Colour.reset,
            )
            pp(f"{desc:<{col_desc}}  ", Colour.reset)
            pp(owner + "\n", Colour.dim_grey)
        pp("\n")

    def _make_tool_fn(self, bound: BoundToolCall):
        """Build a FastMCP-compatible wrapper around a bound engine method."""
        method = bound.method
        meta = bound.meta
        InputModel = params_to_model(method, skip_params={"auth", "request"})

        # `from __future__ import annotations` makes inspect.signature() return
        # ForwardRef strings for all annotations. FastMCP's introspection can't
        # resolve those against an empty globalns, so we evaluate them now using
        # the module globals of the underlying function.
        fn = getattr(method, "__func__", method)
        try:
            resolved_hints = typing.get_type_hints(fn)
        except Exception:
            resolved_hints = {}

        orig_sig = inspect.signature(method)
        expects_ctx = "ctx" in orig_sig.parameters
        expects_auth = "auth" in orig_sig.parameters
        ctx_param = inspect.Parameter(
            "ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Context
        )
        new_params = [ctx_param]
        for name, p in orig_sig.parameters.items():
            if name in ("self", "cls", "ctx", "auth", "request"):
                continue
            resolved_annotation = resolved_hints.get(name, p.annotation)
            new_params.append(p.replace(annotation=resolved_annotation))

        return_annotation = resolved_hints.get("return", orig_sig.return_annotation)
        new_sig = orig_sig.replace(
            parameters=new_params, return_annotation=return_annotation
        )
        new_annotations = {param.name: param.annotation for param in new_params}
        if return_annotation is not inspect.Signature.empty:
            new_annotations["return"] = return_annotation

        async def tool_fn(*args, **kwargs):
            """Authenticate, validate, and invoke one MCP tool call."""
            ctx = args[0] if args else kwargs.pop("ctx")
            validated = InputModel(**kwargs)
            call_kwargs = validated.model_dump()
            if expects_ctx:
                call_kwargs["ctx"] = ctx

            if meta.auth_required:
                try:
                    auth = await self.app.authenticator.require_mcp_context(ctx)
                except RequestError as exc:
                    _, envelope = to_public_error(exc)
                    _safe_log(self.app, exc, envelope)
                    raise PermissionError(
                        json.dumps(envelope.model_dump(mode="json"))
                    ) from exc
                if expects_auth:
                    call_kwargs["auth"] = auth

            try:
                result = method(**call_kwargs)
            except RequestError as exc:
                _, envelope = to_public_error(exc)
                _safe_log(self.app, exc, envelope)
                raise ValueError(json.dumps(envelope.model_dump(mode="json"))) from exc
            except Exception as exc:
                _, envelope = to_public_error(exc)
                _safe_log(self.app, exc, envelope)
                raise ValueError(json.dumps(envelope.model_dump(mode="json"))) from exc
            if asyncio.iscoroutine(result):
                try:
                    result = await result
                except RequestError as exc:
                    _, envelope = to_public_error(exc)
                    _safe_log(self.app, exc, envelope)
                    raise ValueError(
                        json.dumps(envelope.model_dump(mode="json"))
                    ) from exc
                except Exception as exc:
                    _, envelope = to_public_error(exc)
                    _safe_log(self.app, exc, envelope)
                    raise ValueError(
                        json.dumps(envelope.model_dump(mode="json"))
                    ) from exc
            if hasattr(result, "model_dump"):
                return result.model_dump(mode="json")
            if isinstance(result, list) and result and hasattr(result[0], "model_dump"):
                return [r.model_dump(mode="json") for r in result]
            return result

        tool_fn.__name__ = meta.name
        tool_fn.__doc__ = meta.description or (method.__doc__ or "")
        tool_fn.__signature__ = new_sig
        tool_fn.__annotations__ = new_annotations
        return tool_fn

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """Delegate incoming ASGI traffic to the mounted FastMCP app."""
        await self._starlette_app(scope, receive, send)
