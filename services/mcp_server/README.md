# Lighthouse MCP Service

The MCP service is Lighthouse's agent-facing context layer.

Its main purpose is to help coding agents retrieve better context for a task than they can infer from the currently open file or local workspace alone. The long-term focus is search and retrieval for coding work such as:

- architectural decisions and constraints
- deeper codebase understanding
- non-local dependencies and invariants
- relevant files or code regions to inspect before editing

The primary retrieval entrypoint is `get_code_context`.

## Local Setup

From the repository root:

1. Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/).
2. Install workspace dependencies:
   ```shell
   uv sync --all-packages --dev
   ```
3. Copy the MCP env template:
   ```shell
   cp services/mcp_server/.env.example services/mcp_server/.env
   ```
4. Fill in the required settings in `services/mcp_server/.env`.

If you are running locally with the current auth flow, you will usually want:

- a Postgres DSN
- GitHub OAuth client credentials
- a generated `SESSION_ENCRYPTION_KEY`
- a `WEB_CLIENT_URL` that matches the web app

## Configuration

The main environment variables are:

- `DEBUG`
- `CORS_ALLOW_ORIGINS`
- `POSTGRES_DSN`
- `MCP_SERVER_SETTINGS_SSM_PARAMETER`
- `AWS_REGION`
- `GITHUB_OAUTH_CLIENT_ID`
- `GITHUB_OAUTH_CLIENT_SECRET`
- `GITHUB_OAUTH_CALLBACK_URL`
- `SESSION_ENCRYPTION_KEY`
- `WEB_CLIENT_URL`

Configuration behavior:

- explicit environment variables override SSM values
- if `MCP_SERVER_SETTINGS_SSM_PARAMETER` is set, the service loads one JSON settings object from AWS SSM Parameter Store
- `POSTGRES_DSN` controls whether the database is started during app lifespan

## Running the Service

From `services/mcp_server/`:

```shell
uv run uvicorn mcp_server.main:app --reload --host 0.0.0.0 --port 8000 --env-file .env
```

Or from the repository root:

```shell
uv run --directory services/mcp_server uvicorn mcp_server.main:app --reload --host 0.0.0.0 --port 8000 --env-file .env
```

The service exposes:

- HTTP routes on the main FastAPI app
- the MCP server mounted at `/mcp`

At startup, the service pretty-prints both the registered HTTP routes and the registered MCP tools so it is easy to confirm what was discovered.

## Authentication

The service uses one shared bearer-token model for both HTTP and MCP.

### Bootstrap

GitHub OAuth is used to issue a Lighthouse bearer token:

- `GET /v1/auth/github`
- `GET /v1/auth/github/callback`

On successful callback:

- the GitHub user is upserted
- a Lighthouse bearer token is generated
- the browser is redirected back to the web client with the token in the URL fragment

### Protected Calls

Protected HTTP routes and MCP tools expect:

```text
Authorization: Bearer <token>
```

## Current HTTP API

Public routes:

- `GET /health`
- `GET /v1/auth/github`
- `GET /v1/auth/github/callback`

Protected routes:

- `POST /v1/auth/logout`
- `GET /v1/auth/me`
- `POST /v1/user/repos`
- `DELETE /v1/user/repos/{repo_id:path}`
- `POST /v1/search/code-context`

## Current MCP Tools

- `get_current_user`
- `add_user_repo`
- `remove_user_repo`
- `get_code_context`

All current MCP tools require bearer authentication.

## Search Entry Point

The intended main coding-agent entrypoint is `get_code_context`.

It is exposed as:

- HTTP: `POST /v1/search/code-context`
- MCP: `get_code_context`

Current request fields:

- `repository_name`
- `task_description`
- `branch`
- `latest_commit`
- `file_path`
- `start_line`
- `end_line`
- `selected_text`
- `surrounding_context`

Current behavior:

- validates the request
- normalizes key fields
- returns a typed placeholder response with `status = "not_implemented"`

## Repository Management

The service currently supports lightweight repository registration for a user.

Behavior:

- repository input can be either `owner/repo` or a GitHub URL
- repositories are normalized to canonical `owner/repo` form
- repositories are stored globally and uniquely
- removing a repository hides it only for the requesting user
- re-adding a hidden repository unhides it for that user without creating a duplicate record

This is metadata management only for now. It does not yet trigger search indexing or retrieval.

## Development Commands

Format the service:

```shell
ruff format src tests
```

Run the service tests:

```shell
pytest tests
```

Run one test file:

```shell
pytest tests/test_service.py
```

## Notes

- The current tests use a local FastMCP stub to exercise MCP wrappers without depending on the external MCP runtime package during test execution.
- The canonical design doc for this service is [docs/mcp.md](../../docs/mcp.md).
