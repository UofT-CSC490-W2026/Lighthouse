# Lighthouse

Better context for coding agents.

**Team**: Aarya Prakash, Derek Huynh, Merrick Liu, Rhys Balevicius

### Repo Structure

```
monorepo/
├── services/
│   ├── ingestion/          # Data ingestion service
│   ├── search/             # Search layer service
│   ├── mcp/                # MCP service
│   └── web/                # Web service
│
├── packages/               # Shared internal libraries
│   ├── db/                 # Relational DB models & migrations
│   ├── vectordb/           # Vector DB client & helpers
│   └── shared/             # Common utilities (logging, config, auth)
│
├── infra/                  # Infrastructure as code
│
├── scripts/                # Dev tooling scripts
│
├── .github/
│   └── workflows/          # CI per service (path filters)
│
├── pyproject.toml          # Root: dev tools only (ruff, mypy, pytest)
└── uv.lock                 # Single lockfile for the whole repo
```

### Setup Instructions

1. Install [Docker Desktop](https://docs.docker.com/desktop/)
2. Install [Temporal CLI](https://temporal.io/setup/install-temporal-cli) for running temporal locally.
3. Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) for Python package management.
4. Run `uv sync` to install dependencies for the entire monorepo.

### Running the Services

1. Run `docker compose up -d` to start Postgres and Milvus.
2. Run `temporal server start-dev` to start the Temporal server.
3. For running a `service`, use `uv run --package <service> ...`.
