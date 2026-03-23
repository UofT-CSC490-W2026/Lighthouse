from __future__ import annotations

from peewee import Database, DatabaseProxy, Model
from playhouse.db_url import connect as connect_database_url


class MCPDatabase:
    """Own the configured Peewee database and its lifecycle helpers."""

    proxy = DatabaseProxy()

    def __init__(self, database_url: str | None = None) -> None:
        """Create a database wrapper with an optional initial DSN."""
        self.database_url = (database_url or "").strip()
        self._database: Database | None = None

    @property
    def database(self) -> Database:
        """Return the initialized Peewee database instance."""
        if self._database is None:
            raise RuntimeError("Database has not been initialized.")
        return self._database

    @property
    def is_configured(self) -> bool:
        """Report whether a non-empty database URL has been configured."""
        return bool(self.database_url)

    @property
    def is_initialized(self) -> bool:
        """Report whether the concrete Peewee database has been created."""
        return self._database is not None

    @property
    def is_connected(self) -> bool:
        """Report whether the database is initialized and currently open."""
        return self.is_initialized and not self.database.is_closed()

    def configure(self, database_url: str | None) -> None:
        """Update the database URL used for later initialization."""
        self.database_url = (database_url or "").strip()

    def initialize(self) -> Database:
        """Instantiate and proxy-bind the configured Peewee database."""
        if not self.database_url:
            raise RuntimeError("POSTGRES_DSN must be configured before initializing the database.")

        if self._database is None:
            self._database = connect_database_url(self.database_url, autoconnect=False)
            self.proxy.initialize(self._database)

        return self._database

    def connect(self, *, reuse_if_open: bool = True) -> Database:
        """Open the configured database connection and return it."""
        database = self.initialize()
        database.connect(reuse_if_open=reuse_if_open)
        return database

    def close(self) -> None:
        """Close the database connection if it is currently open."""
        if self._database is None:
            return

        if not self._database.is_closed():
            self._database.close()

    def connection_context(self):
        """Return a Peewee connection context for threaded query helpers."""
        return self.database.connection_context()


class BaseModel(Model):
    """Base Peewee model bound to the shared database proxy."""

    class Meta:
        """Bind all derived models to the MCP database proxy."""

        database = MCPDatabase.proxy
