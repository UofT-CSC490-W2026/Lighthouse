# MCP Server

The MCP server is Lighthouse's agent-facing context layer. Its purpose is to help coding agents retrieve better context for a task than they can infer from the currently open file or local workspace alone — architectural decisions and constraints, deeper codebase understanding, non-local dependencies and invariants, and relevant files or code regions to inspect before editing.

The primary retrieval entrypoint is `search_code`.

## Architecture

The service is built on **FastAPI** with **FastMCP** and exposes two parallel protocol surfaces:

- **HTTP REST routes** on the main FastAPI app
- **MCP tools** mounted at `/mcp`

Both surfaces are driven by the same `Engine` class, which composes four subengines:

```
                    Coding Agents
                   /              \
            HTTP Routes         MCP Tools
                   \              /
                    Engine
              /    /    \    \
        Auth  Search  User  Wiki
          |      |      |     |
          +------+------+-----+
                 |
       PostgreSQL DB    Search Service    Ingestion Service
```

**Key source paths:**

| Path | Purpose |
|------|---------|
| `services/mcp_server/src/mcp_server/main.py` | FastAPI app initialization and lifespan |
| `services/mcp_server/src/mcp_server/engine/engine.py` | Engine class composing subengines |
| `services/mcp_server/src/mcp_server/engine/auth.py` | GitHub OAuth and token lifecycle |
| `services/mcp_server/src/mcp_server/engine/search.py` | Code context retrieval |
| `services/mcp_server/src/mcp_server/engine/user.py` | User profile and repository management |
| `services/mcp_server/src/mcp_server/engine/wiki.py` | Wiki generation and retrieval |
| `services/mcp_server/src/mcp_server/routers/http/handler.py` | HTTP route registration |
| `services/mcp_server/src/mcp_server/routers/mcp/handler.py` | MCP tool registration |
| `services/mcp_server/src/mcp_server/utilities/config/env.py` | Configuration and settings |
| `services/mcp_server/src/mcp_server/utilities/decorators.py` | `@httproute` / `@toolcall` decorators |

**Route registration pattern:** Methods decorated with `@httproute` or `@toolcall` are introspected at startup via `collect_routables()` and `collect_toolcalls()`, and auto-registered with FastAPI and FastMCP respectively. The service pretty-prints all discovered routes and tools to stdout on startup.

## Local Setup

From the repository root:

1. Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/).
2. Install workspace dependencies:
   ```shell
   uv sync --all-packages --dev
   ```
3. Copy the env template:
   ```shell
   cp services/mcp_server/.env.example services/mcp_server/.env
   ```
4. Fill in the required settings in `services/mcp_server/.env` (see [Configuration](#configuration) below).

To generate the required secret values:

```shell
# SESSION_ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# INTERNAL_SERVICE_TOKEN
python -c "import secrets; print(secrets.token_hex(32))"
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `true` | Enable debug mode |
| `CORS_ALLOW_ORIGINS` | `["http://localhost:5173"]` | Allowed CORS origins |
| `POSTGRES_DSN` | — | PostgreSQL connection string. Required; controls whether DB is initialized on startup. |
| `GITHUB_OAUTH_CLIENT_ID` | — | GitHub OAuth app client ID |
| `GITHUB_OAUTH_CLIENT_SECRET` | — | GitHub OAuth app client secret |
| `GITHUB_OAUTH_CALLBACK_URL` | `http://localhost:8000/v1/auth/github/callback` | GitHub OAuth redirect URL. Must match the registered OAuth app callback. |
| `SESSION_ENCRYPTION_KEY` | — | Fernet key for encrypting bearer tokens at rest. Generate with the command above. |
| `SESSION_TTL_HOURS` | `168` | Session token lifetime in hours (default: 7 days) |
| `WEB_CLIENT_URL` | `http://localhost:5173` | Frontend URL for post-OAuth redirect |
| `MCP_SERVER_SETTINGS_SSM_PARAMETER` | — | AWS SSM parameter name for remote JSON config. Explicit env vars override SSM values. |
| `AWS_REGION` | — | AWS region for SSM |
| `SEARCH_SERVICE_URL` | `http://localhost:8002` | Base URL of the search service |
| `INGESTION_SERVICE_URL` | `http://localhost:8001` | Base URL of the ingestion service |
| `INTERNAL_SERVICE_TOKEN` | `""` | Bearer token for service-to-service calls to ingestion/search |

## Running the Service

From `services/mcp_server/`:

```shell
uv run uvicorn mcp_server.main:app --reload --host 0.0.0.0 --port 8000 --env-file .env
```

Or from the repository root:

```shell
uv run --directory services/mcp_server uvicorn mcp_server.main:app --reload --host 0.0.0.0 --port 8000 --env-file .env
```

The service listens on port `8000` by default and mounts the MCP server at `/mcp`.

## Authentication

The service uses one shared bearer-token model for both HTTP and MCP calls.

### Bootstrap

GitHub OAuth issues a Lighthouse bearer token:

1. `GET /v1/auth/github` — redirects the user to GitHub for authorization
2. `GET /v1/auth/github/callback` — GitHub redirects here after consent; the service upserts the user, generates a bearer token, and redirects the browser back to `WEB_CLIENT_URL` with the token in the URL fragment

### Token types

| Type | Lifetime | Use case |
|------|---------|---------|
| Session token | `SESSION_TTL_HOURS` (default 7 days) | Web client requests |
| MCP token | Long-lived (revocable) | Agent / MCP client configuration |

MCP tokens are managed via:

- `GET /v1/auth/mcp-token` — retrieve the current MCP token
- `POST /v1/auth/mcp-token` — generate or rotate the MCP token
- `DELETE /v1/auth/mcp-token` — revoke the MCP token

### Protected calls

All protected routes and MCP tools expect:

```
Authorization: Bearer <token>
```

## HTTP API Reference

### Public routes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe |
| `GET` | `/v1/auth/github` | Start GitHub OAuth flow |
| `GET` | `/v1/auth/github/callback` | Complete GitHub OAuth and issue bearer token |

### Protected routes

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/auth/logout` | Invalidate current session token |
| `GET` | `/v1/auth/me` | Return the authenticated user |
| `GET` | `/v1/auth/mcp-token` | Get the current long-lived MCP token |
| `POST` | `/v1/auth/mcp-token` | Generate or rotate the long-lived MCP token |
| `DELETE` | `/v1/auth/mcp-token` | Revoke the long-lived MCP token |
| `POST` | `/v1/search/search-code` | Retrieve indexed code context for a query |
| `GET` | `/v1/user/repos` | List repositories visible to the current user |
| `POST` | `/v1/user/repos` | Add a repository to the index (or unhide it) |
| `POST` | `/v1/user/repos/{full_name}/branches` | Add branches to an already-indexed repository |
| `DELETE` | `/v1/user/repos/{full_name}` | Hide a repository for the current user |
| `POST` | `/v1/wiki/generate` | Trigger wiki generation for a repository branch |
| `GET` | `/v1/wiki/{repository_name}` | Retrieve generated wiki pages |
| `POST` | `/v1/wiki/search` | Search wiki documentation |

## MCP Tools Reference

All MCP tools require bearer authentication.

| Tool | Description | Parameters |
|------|-------------|-----------|
| `search_code` | Retrieve indexed code context for a coding task | `repository_name` (str), `query` (str), `branch` (str, default `"main"`), `file_path` (str\|None), `top_k` (int 1–15, default `5`) |
| `search_wiki` | Search generated wiki documentation | `repository_name` (str), `query` (str), `branch` (str, default `"main"`), `top_k` (int 1–15, default `5`) |
| `list_user_repos` | List repositories visible to the current user | — |
| `add_user_repo` | Add a repository to the shared index, or unhide it | `repo_url` (str), `branches` (list[str], default `[]`) |
| `add_user_repo_branches` | Add branches to an already-indexed repository | `full_name` (str), `branches` (list[str]) |
| `remove_user_repo` | Hide a repository for the current user (does not delete globally) | `full_name` (str) |
| `get_current_user` | Return the authenticated Lighthouse user | — |
| `get_wiki` | Retrieve generated wiki pages for a repository | `repository_name` (str), `branch` (str, default `"main"`) |

**Agent guidance** (from MCP server instructions):

- Use `search_code` as the primary entrypoint for coding context retrieval.
- Call `list_user_repos` first when it is unclear which repositories are available.
- Use `get_wiki` / `search_wiki` for repository-level documentation and architectural context.
- Skip Lighthouse when the task is fully local to files already visible in the workspace.

## Key Response Schemas

### `CodeContextResponse`

Returned by `search_code` and `POST /v1/search/search-code`.

```python
{
  "status": "ok" | "error" | "not_implemented",
  "message": str,
  "repository_name": str,
  "branch": str,
  "query": str,
  "snippets": [
    {
      "context_source": "code" | "wiki" | "llm_combined",
      "file_path": str | None,
      "start_line": int | None,
      "end_line": int | None,
      "content": str,
      "reason": str | None,
      "page_title": str | None,
      "slug": str | None,
      "section_path": str | None
    }
  ]
}
```

### `UserRepoResponse`

Returned by repository management tools and routes.

```python
{
  "id": str,
  "github_repo_id": int,
  "full_name": str,
  "repo_url": str,
  "display_name": str,
  "added_at": datetime,
  "index_status": "PENDING" | "INDEXING" | "INDEXED" | "FAILED" | None,
  "branches": [
    {
      "branch_name": str,
      "status": "PENDING" | "INDEXING" | "INDEXED" | "FAILED"
    }
  ]
}
```

## Development Commands

Format:

```shell
ruff format src tests
```

Run all tests:

```shell
pytest tests
```

Run one test file:

```shell
pytest tests/unit/test_decorators.py
```

The test suite uses a local FastMCP stub to exercise MCP tool wrappers without requiring the external MCP runtime.
