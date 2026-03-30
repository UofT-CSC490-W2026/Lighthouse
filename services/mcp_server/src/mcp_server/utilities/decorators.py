from __future__ import annotations

import inspect
import typing
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, Field, create_model
from pydantic.fields import FieldInfo


@dataclass(frozen=True, slots=True)
class ToolCallMeta:
    """Describe how a bound method should be exposed as an MCP tool."""

    name: str
    description: str = ""
    auth_required: bool = True


@dataclass(frozen=True, slots=True)
class RouteMeta:
    """Describe how a bound method should be exposed as an HTTP route."""

    method: str
    path: str
    name: str = ""
    description: str = ""
    auth_required: bool = True


@dataclass(slots=True)
class BoundToolCall:
    """Pair a tool declaration with the bound method and its owner object."""

    meta: ToolCallMeta
    method: Callable[..., Any]
    owner: Any


@dataclass(slots=True)
class BoundRoute:
    """Pair a route declaration with the bound method and its owner object."""

    meta: RouteMeta
    method: Callable[..., Any]
    owner: Any


def toolcall(
    name: str,
    description: str = "",
    *,
    auth_required: bool = True,
) -> Callable:
    """Mark a method as an MCP toolcall by stamping __toolcall__ onto the function."""

    def decorator(fn: Callable) -> Callable:
        """Attach MCP tool metadata to the decorated function."""
        fn.__toolcall__ = ToolCallMeta(
            name=name,
            description=description,
            auth_required=auth_required,
        )
        return fn

    return decorator


def httproute(
    method: str,
    path: str,
    *,
    name: str = "",
    description: str = "",
    auth_required: bool = True,
) -> Callable:
    """Mark a method as an HTTP route by stamping __httproute__ onto the function."""

    def decorator(fn: Callable) -> Callable:
        """Attach HTTP route metadata to the decorated function."""
        fn.__httproute__ = RouteMeta(
            method=method.upper(),
            path=path,
            name=name,
            description=description,
            auth_required=auth_required,
        )
        return fn

    return decorator


def routable(
    method: str,
    path: str,
    *,
    name: str = "",
    description: str = "",
    auth_required: bool = True,
) -> Callable:
    """Backward-compatible alias for the HTTP route decorator."""

    return httproute(
        method=method,
        path=path,
        name=name,
        description=description,
        auth_required=auth_required,
    )


def collect_toolcalls(*objects: Any) -> dict[str, BoundToolCall]:
    """
    Walk each object's attributes and collect all methods marked with @toolcall.
    Returns {tool_name: BoundToolCall}. Later entries win on name collision.
    """
    result: dict[str, BoundToolCall] = {}
    for obj in objects:
        for attr_name in dir(obj):
            if attr_name.startswith("__"):
                continue
            try:
                attr = getattr(obj, attr_name)
            except AttributeError:
                continue
            fn = getattr(attr, "__func__", attr)
            meta: ToolCallMeta | None = getattr(fn, "__toolcall__", None)
            if meta is not None and callable(attr):
                result[meta.name] = BoundToolCall(meta=meta, method=attr, owner=obj)
    return result


def collect_routables(*objects: Any) -> dict[str, BoundRoute]:
    """
    Walk each object's attributes and collect all methods marked with @httproute.
    Returns {"METHOD path": BoundRoute}. Later entries win on name collision.
    """
    result: dict[str, BoundRoute] = {}
    for obj in objects:
        for attr_name in dir(obj):
            if attr_name.startswith("__"):
                continue
            try:
                attr = getattr(obj, attr_name)
            except AttributeError:
                continue
            fn = getattr(attr, "__func__", attr)
            meta: RouteMeta | None = getattr(fn, "__httproute__", None)
            if meta is not None and callable(attr):
                route_key = f"{meta.method} {meta.path}"
                result[route_key] = BoundRoute(meta=meta, method=attr, owner=obj)
    return result


_EMPTY = inspect.Parameter.empty


def params_to_model(
    method: Callable,
    *,
    skip_params: set[str] | None = None,
) -> type[BaseModel]:
    """
    Build a Pydantic input model from the signature of method, skipping
    injected parameters such as self and ctx.

    Each parameter becomes a model field:
      - Annotated with a type: that type is used.
      - Has a default: the field is optional with that default.
      - Neither: Any with no default (required).

    The generated class is named <MethodName>Input.
    """
    sig = inspect.signature(method)
    fn = getattr(method, "__func__", method)
    try:
        resolved_hints = typing.get_type_hints(fn, include_extras=True)
    except Exception:
        resolved_hints = {}

    field_definitions: dict[str, Any] = {}
    ignored_params = {"self", "cls", "ctx"}
    if skip_params:
        ignored_params.update(skip_params)

    for param_name, param in sig.parameters.items():
        if param_name in ignored_params:
            continue

        annotation = resolved_hints.get(param_name, param.annotation)
        if annotation is _EMPTY:
            annotation = Any
        has_default = param.default is not _EMPTY

        if has_default:
            field_definitions[param_name] = (annotation, Field(default=param.default))
        else:
            field_definitions[param_name] = (annotation, FieldInfo())

    fn_name = getattr(method, "__name__", "Method")
    model_name = f"{fn_name.replace('_', ' ').title().replace(' ', '')}Input"

    return create_model(model_name, **field_definitions)
