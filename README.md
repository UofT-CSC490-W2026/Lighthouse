# Lighthouse

<!-- coverage:start -->

![Test Coverage](https://img.shields.io/badge/test%20coverage-100.00%25-brightgreen)

<!-- coverage:end -->

Better context for coding agents.

**Team**: Aarya Prakash, Derek Huynh, Merrick Liu, Rhys Balevicius

### Repo Structure

```
monorepo/
├── services/
│   ├── ingestion/          # Data ingestion service
│   ├── search/             # Search layer service
│   ├── mcp_server/         # MCP server (agent-facing API)
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
2. Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) for Python package management.
3. Run `uv sync --all-packages --dev` to install dependencies for the entire monorepo.

### Running the Services

1. Run `docker compose up -d` to start Postgres, Milvus, Temporal, and other services.
2. For running a `service`, use `uv run --package <service> ...`.

### Running Tests

```shell
uv run pytest

# Run tests with coverage
uv run pytest --cov

# Run unit/integration/e2e tests
uv run pytest -m <unit|integration|e2e>
```
