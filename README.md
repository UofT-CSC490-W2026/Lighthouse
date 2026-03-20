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
