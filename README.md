# Lighthouse

<!-- coverage:start -->

[![Tests](https://github.com/UofT-CSC490-W2026/Lighthouse/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/UofT-CSC490-W2026/Lighthouse/actions/workflows/tests.yml)
![Test Coverage](https://img.shields.io/badge/test%20coverage-97.27%25-brightgreen)

<!-- coverage:end -->

Better context for coding agents.

**Team**: Aarya Prakash, Derek Huynh, Merrick Liu, Rhys Balevicius

## Repo Structure

```
lighthouse/
├── services/
│   ├── ingestion/          # Data ingestion service
│   ├── search/             # Search layer service
│   ├── mcp_server/         # MCP server (agent-facing API)
│   └── web/                # Web frontend
│
├── packages/               # Shared internal libraries
│   ├── db/                 # Relational DB models & migrations
│   ├── embedding/          # Embedding providers
│   ├── eval/               # Evaluation framework (SWE-bench, synthetic benchmarks)
│   ├── llm/                # LLM provider clients
│   ├── shared/             # Common utilities (logging, config, auth)
│   ├── testing/            # Shared test fixtures and helpers
│   └── vectordb/           # Vector DB client & helpers
│
├── docs/                   # Architecture and operational documentation
│
├── docker/                 # Docker images for local dev (e.g. Postgres)
│
├── infra/                  # Infrastructure as code
│
├── scripts/                # Dev tooling scripts
│
├── assignments/            # Course materials (not product code)
│
├── .github/
│   └── workflows/          # CI (path filters)
│
├── docker-compose.yml      # Local stack orchestration
├── pyproject.toml          # Workspace manifest & dev tooling (pytest, ruff, ty)
└── uv.lock                 # Lockfile for Python dependencies
```

## Setup Instructions

### Prerequisites

- [Docker Desktop](https://docs.docker.com/desktop/) for containerization.
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) for Python package management.
- [`bun`](https://bun.sh/docs/installation) for JavaScript package management.
- [`Terraform`](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli) for infrastructure as code.
- [`ngrok`](https://ngrok.com/download) for local tunneling. Install this if you want to use the `/webhook` endpoint of the ingestion service.

### Setup

1. Run `uv sync --all-packages --dev` to install dependencies for the entire monorepo.
2. Run `cd services/web && bun install` to install dependencies for the web service.
3. Run `scripts/setup-local-env-files.sh` to setup local `.env` files for all services.

**You will still need to get the following secrets from the team**:

```bash
# For the ingestion and search services
OPENAI_API_KEY=

# For the search service
COHERE_API_KEY=

# For the MCP server
GITHUB_OAUTH_CLIENT_ID=
GITHUB_OAUTH_CLIENT_SECRET=
GITHUB_OAUTH_CALLBACK_URL=
```

## Running Lighthouse Locally

Run `docker compose up -d` to start all services (see `docker-compose.yml` for more details). The services will be available at the following URLs:

- Ingestion service: `http://localhost:8001`
- Search service: `http://localhost:8002`
- MCP server: `http://localhost:8000`
- Web service: `http://localhost:3000`

**Setting up webhooks:** If you want to use the `/webhook` endpoint of the ingestion service, you will need to set up a webhook in your GitHub repository. You can do this by going to the repository settings and clicking on "Webhooks". Then, you can add a new webhook with the following URL, `http://<your-ngrok-url>/webhook`, and your webhook secret (in the `.env` file of the ingestion service).

## Documentation

You can find documentation in the `docs/` directory. For the most part, it mirrors the structure of the repository. For example, the documentation for each package is in the `docs/packages/<package>/` directory.

Below are some key documentation:

- [Search Service](docs/services/search.md)
- [Ingestion Service](docs/services/ingestion.md)
- [MCP Server](docs/services/mcp_server.md)
- [Web Service](docs/services/web.md)
- [Evaluation Framework](docs/evaluation.md)
- [Testing Guide](docs/testing.md)

## Running Tests

```shell
uv run pytest

# Run tests with coverage
uv run pytest --cov

# Run unit/integration/e2e tests
uv run pytest -m <unit|integration|e2e>
```
