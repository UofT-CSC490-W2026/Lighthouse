from __future__ import annotations

from logging import Logger
from typing import TYPE_CHECKING

from .auth import AuthEngine
from .search import SearchEngine
from .user import UserEngine
from .wiki import WikiEngine
from ..utilities import get_logger, httproute

if TYPE_CHECKING:
    from ..main import App


class Engine:
    """Compose the app's service subobjects and shared registrations."""

    app: App
    log: Logger
    auth: AuthEngine
    search: SearchEngine
    user: UserEngine
    wiki: WikiEngine

    def __init__(self, app: App) -> None:
        """Create the engine and its service subobjects for the given app."""
        self.app = app
        self.log = get_logger(__name__)
        self.auth = AuthEngine(self)
        self.search = SearchEngine(self)
        self.user = UserEngine(self)
        self.wiki = WikiEngine(self)

    def registries(self) -> tuple[object, ...]:
        """Return the objects that contribute HTTP routes and MCP tools."""
        return (self, self.auth, self.user, self.search, self.wiki)

    @httproute(
        "GET",
        "/health",
        name="health",
        description="Liveness probe for the MCP service.",
        auth_required=False,
    )
    def health(self) -> dict[str, bool]:
        """Report that the service process is alive."""
        return {"ok": True}
