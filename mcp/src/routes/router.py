"""Top-level route registry for MCP public and tool endpoints."""

from fastapi import FastAPI

from .tool import tool_router
from .public import public_router
from ..utils import pretty_print, Colour
from ..utils.logger import get_logger

log = get_logger(__name__)


class Router:
    """Attach and display grouped routers for MCP startup."""

    def __init__(self):
        """Construct router registry metadata used at app boot."""
        self.routers: list[tuple[str, Colour, object]] = [
            ("public", Colour.green, public_router),
            ("tools", Colour.bold_cyan, tool_router),
        ]

    def attach(self, app: FastAPI):
        """Attach all configured routers to the FastAPI application."""
        log.info("MCP router attach: registering %d routers", len(self.routers))
        for _, _, router in self.routers:
            app.include_router(router)
        self._display()
        log.info("MCP routes registered: %s", self._get_paths())

    def _get_methods(self) -> set[str]:
        """Collect unique HTTP methods exposed by configured routers."""
        methods = set()
        for _, _, router in self.routers:
            for route in router.routes:
                if hasattr(route, "methods"):
                    methods.update(route.methods)
        return methods

    def _get_paths(self) -> list[str]:
        """Collect all route paths exposed by configured routers."""
        paths = []
        for _, _, router in self.routers:
            for route in router.routes:
                if hasattr(route, "path"):
                    paths.append(route.path)
        return paths

    def _display(self):
        """Render a startup summary table of registered routes."""
        if not self._get_paths():
            return

        method_padding = max(len(method) for method in self._get_methods()) + 2
        route_padding = max(len(path) for path in self._get_paths()) + 2

        for router_tag, color, router in self.routers:
            for route in router.routes:
                if hasattr(route, "methods"):
                    for method in route.methods:
                        pretty_print(
                            method.ljust(method_padding, " "), Colour.bold_cyan
                        )
                        pretty_print(
                            f"{route.path}".ljust(route_padding, " "),
                            Colour.dim_grey,
                            end="",
                        )
                        pretty_print(router_tag, color, end="\n")
