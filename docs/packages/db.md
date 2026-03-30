# `db`

Shared database package for Lighthouse services. It wraps Peewee connection management and exposes the canonical relational models used by ingestion, search, and the MCP server.

## What this package contains

- `DatabaseManager`: owns the configured Peewee database, initializes the shared `DatabaseProxy`, and exposes lifecycle helpers.
- `BaseModel`: base model bound to the shared proxy.
- Auth and repository models:
  - `User`
  - `Session`
  - `Repository`
  - `UserHiddenRepository`
- Indexing models:
  - `IndexedBranch`
  - `Chunk`
  - `IndexedFile`
  - `StagingChunk`
- Wiki models:
  - `WikiGeneration`
  - `WikiPage`
  - `StagingWikiPage`

All of these are re-exported from `db.__init__`, so services can import directly from `db`.

## Installation boundary

Package path: `packages/db`

Main dependencies:

- `peewee`
- `playhouse.db_url`
- `psycopg2-binary`
- `sqlalchemy` and `alembic` are present in the package dependencies, but the runtime code in this package uses Peewee models and `DatabaseProxy`.

## DatabaseManager

`DatabaseManager` is the entry point every service uses to bind models to a concrete database URL.

### Responsibilities

- Stores the configured DSN.
- Lazily creates the Peewee database instance.
- Initializes the shared `DatabaseProxy`.
- Opens and closes connections.
- Exposes `connection_context()` for scoped query execution.

### Core API

```python
from db import DatabaseManager

db = DatabaseManager("postgresql://user:pass@localhost:5432/lighthouse")
db.connect()

try:
    with db.connection_context():
        ...
finally:
    db.close()
```

### Behavior notes

- `initialize()` raises `RuntimeError` if no database URL is configured.
- The proxy is initialized only once per manager instance.
- `database` raises `RuntimeError` until initialization has happened.
- `connect(reuse_if_open=True)` is safe to call in service startup paths.

## Data model overview

### Auth and repository state

- `User`: GitHub identity plus encrypted API and MCP token metadata.
- `Session`: encrypted GitHub access token for a user session.
- `Repository`: globally indexed repository record keyed by GitHub repo id and full name.
- `UserHiddenRepository`: per-user hide state without deleting the shared repository row.

### Code indexing state

- `IndexedBranch`: per-repository, per-branch indexing status and commit bookkeeping.
- `Chunk`: persisted code chunks used for retrieval and search.
- `IndexedFile`: active publish id for a file on a branch.
- `StagingChunk`: temporary rows used between ingestion workflow steps before publish.

### Wiki generation state

- `WikiGeneration`: one wiki generation run for a repository branch.
- `WikiPage`: persisted generated wiki pages.
- `StagingWikiPage`: temporary wiki rows before final publish.

## Common usage patterns

### Service startup

Search, ingestion, and MCP server startup all follow the same pattern:

```python
from db import DatabaseManager

db = DatabaseManager(settings.postgres_dsn)
db.connect()
```

### Creating tables in tests or local scripts

```python
from db import DatabaseManager, Repository, Chunk, IndexedFile

db = DatabaseManager("sqlite:///local.db")
db.connect()
db.database.create_tables([Repository, Chunk, IndexedFile])
```

### Working inside a connection context

```python
from db import Repository

with db.connection_context():
    repo = Repository.get_or_none(Repository.full_name == "owner/repo")
```

## Operational assumptions

- The package expects a valid DSN string, typically supplied via `postgres_dsn` in service settings.
- Model binding is global through `DatabaseManager.proxy`, so tests that replace the active database must rebind carefully.
- Staging tables are part of the ingestion pipeline contract. They are not archival storage.

## Related packages

- `shared`: request/response schemas and config constants used by services around this package.
- `vectordb`: vector storage for embeddings associated with `Chunk` and wiki content.
- `embedding`: creates the embeddings later stored in Milvus.
