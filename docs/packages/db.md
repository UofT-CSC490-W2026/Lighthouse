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

## Database migrations

The `db` package is the source of truth for Lighthouse's relational schema, so any schema migration should be derived from changes to the models in this package.

### Current state

- The package declares `alembic` as a dependency.
- The runtime model layer is implemented with Peewee, not SQLAlchemy ORM models.
- Tests and local profiling utilities sometimes create tables directly from the Peewee models, but that is a convenience for isolated environments, not a production migration strategy.

### Practical migration rule

When you change any of these models:

- `User`
- `Session`
- `Repository`
- `UserHiddenRepository`
- `IndexedBranch`
- `Chunk`
- `IndexedFile`
- `StagingChunk`
- `WikiGeneration`
- `WikiPage`
- `StagingWikiPage`

you should treat that as a schema change and add or update the corresponding database migration before relying on the new shape in a deployed service.

### What belongs in a migration

Typical changes include:

- creating or dropping tables
- adding, renaming, or removing columns
- changing nullability or uniqueness constraints
- adding or changing indexes
- backfilling data needed by new application logic

### How to run migrations

Alembic is configured under `packages/db/alembic.ini` with scripts in `packages/db/alembic/versions`.

Run migrations from the package directory:

```bash
cd packages/db
alembic upgrade head
```

If you are using the workspace-managed environment, the equivalent command is:

```bash
cd packages/db
uv run alembic upgrade head
```

### Connection resolution

- If `POSTGRES_DSN` is set, Alembic uses that value.
- If `POSTGRES_DSN` starts with `postgresql://`, the Alembic env rewrites it to `postgresql+asyncpg://` for the async engine.
- If `POSTGRES_DSN` is not set, Alembic falls back to the `sqlalchemy.url` value in `packages/db/alembic.ini`.

Example:

```bash
cd packages/db
POSTGRES_DSN=postgresql://lighthouse:lighthouse@localhost:5432/lighthouse uv run alembic upgrade head
```

### Important distinction

`db.database.create_tables(...)` is appropriate for tests, throwaway local databases, and profiling scripts. It should not be treated as a substitute for a versioned migration path in shared or production environments.

## Operational assumptions

- The package expects a valid DSN string, typically supplied via `postgres_dsn` in service settings.
- Model binding is global through `DatabaseManager.proxy`, so tests that replace the active database must rebind carefully.
- Staging tables are part of the ingestion pipeline contract. They are not archival storage.

## Related packages

- `shared`: request/response schemas and config constants used by services around this package.
- `vectordb`: vector storage for embeddings associated with `Chunk` and wiki content.
- `embedding`: creates the embeddings later stored in Milvus.
