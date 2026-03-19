# Lighthouse

Better context for coding agents.

**Team**: Aarya Prakash, Derek Huynh, Merrick Liu, Rhys Balevicius

### Repo Structure

```
monorepo/
├── services/
│   ├── ingestion/          # Data ingestion service
│   │   ├── src/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   ├── search/             # Search layer service
│   │   ├── src/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   ├── mcp/                # MCP service
│   │   ├── src/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   └── web/                # Web service
│       ├── src/
│       ├── tests/
│       ├── Dockerfile
│       └── pyproject.toml
│
├── packages/               # Shared internal libraries
│   ├── db/                 # Relational DB models & migrations
│   │   ├── src/
│   │   │   └── db/
│   │   │       ├── models/
│   │   │       ├── migrations/    # Alembic migrations live here
│   │   │       └── session.py
│   │   └── pyproject.toml
│   ├── vectordb/           # Vector DB client & helpers
│   │   ├── src/
│   │   │   └── vectordb/
│   │   │       ├── client.py
│   │   │       └── collections.py
│   │   └── pyproject.toml
│   └── shared/             # Common utilities (logging, config, auth)
│       ├── src/
│       │   └── shared/
│       │       ├── config.py
│       │       ├── logging.py
│       │       └── models.py      # Shared Pydantic schemas
│       └── pyproject.toml
│
├── infra/                  # Infrastructure as code
│   ├── docker-compose.yml
│   ├── docker-compose.dev.yml
│   └── k8s/
│
├── scripts/                # Dev tooling scripts
│   ├── bootstrap.sh
│   └── migrate.sh
│
├── .github/
│   └── workflows/          # CI per service (path filters)
│
├── pyproject.toml          # Root: dev tools only (ruff, mypy, pytest)
└── uv.lock                 # Single lockfile for the whole repo
```

s
