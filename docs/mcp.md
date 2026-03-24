# MCP Service

## Purpose

The MCP service is Lighthouse's agent-facing context layer.

Its main job is to help coding agents get better context for a task than they can infer from the currently open file alone. The intended focus is retrieval for coding work such as:

- architectural decisions and constraints
- deeper codebase understanding
- non-local dependencies and invariants
- relevant files or code regions to inspect before making a change

Today, the primary search entrypoint is `get_code_context`. The surrounding auth and repository-management APIs exist to support that retrieval workflow.

## Current State

The service has been refactored around:

- a top-level `App` that owns shared state
- an `Engine` with service subobjects for `auth`, `user`, and `search`
- decorator-based registration for both HTTP routes and MCP tools
- one shared bearer-token authentication path for HTTP and MCP
- Peewee models and a retained `DatabaseManager` object on the app
- typed settings with SSM-backed defaults and environment-variable overrides

Important current limitation:

- `get_code_context` is still a placeholder. It validates and captures the request envelope but does not yet perform real retrieval.

## Source Layout

The current MCP service package lives under `services/mcp_client/src/mcp_client`:

```text
services/mcp_client/src/mcp_client/
  main.py
  engine/
    engine.py
    auth.py
    user.py
    search.py
  models/
    database.py
    auth.py
  routers/
    http/
      handler.py
    mcp/
      handler.py
  utilities/
    auth.py
    config/
      env.py
    decorators.py
    errors.py
    logging/
```

High-level responsibility split:

- `main.py`: app bootstrap, lifespan, router mounting, database startup/shutdown
- `engine/`: business-facing service methods that are exposed through decorators
- `models/`: Peewee database models and database lifecycle wrapper
- `routers/`: dynamic HTTP and MCP handler generation
- `utilities/`: auth, config, decorators, request errors, and logging

## Architecture

### `App`

`services/mcp_client/src/mcp_client/main.py` defines `App`, a `FastAPI` subclass that owns:

- `settings`
- `database`
- `authenticator`
- `engine`

During the app lifespan it:

1. creates the HTTP handler
2. creates the MCP handler
3. opens the database connection if `POSTGRES_DSN` is configured
4. mounts the generated HTTP router and MCP ASGI app
5. starts the FastMCP session manager
6. shuts MCP down and closes the database on exit

### `Engine`

`services/mcp_client/src/mcp_client/engine/engine.py` is the composition root for service logic. It exposes:

- `auth: AuthEngine`
- `user: UserEngine`
- `search: SearchEngine`

`Engine.registries()` returns the objects that should be scanned for decorated HTTP routes and MCP tools.

### Decorator-Driven Exposure

The service uses shared metadata decorators from `services/mcp_client/src/mcp_client/utilities/decorators.py`:

- `@httproute(method, path, ...)`
- `@toolcall(name, ...)`

Both decorators default to `auth_required=True`.

This gives the codebase one consistent pattern:

- write the business-facing method on an engine service
- mark it with HTTP and/or MCP decorators
- let the transport handlers register and wrap it automatically

### HTTP Handler

`services/mcp_client/src/mcp_client/routers/http/handler.py`:

- discovers all decorated HTTP routes from `engine.registries()`
- builds a FastAPI endpoint wrapper for each route
- injects auth before the handler runs
- translates `RequestError` into `HTTPException`
- pretty-prints the registered routes at startup

### MCP Handler

`services/mcp_client/src/mcp_client/routers/mcp/handler.py`:

- discovers all decorated MCP tools from `engine.registries()`
- builds a FastMCP wrapper for each tool
- injects auth before the handler runs
- validates inputs using a generated Pydantic model
- pretty-prints the registered tools at startup

The MCP handler also carries the server description shown to clients and agents.

## Authentication Model

The service uses one shared bearer-token model for both HTTP and MCP.

### Bootstrap Flow

Authentication starts with GitHub OAuth:

- `GET /v1/auth/github`
- `GET /v1/auth/github/callback`

Flow:

1. the service generates an OAuth state token
2. it redirects the caller to GitHub
3. GitHub redirects back to `/v1/auth/github/callback`
4. the callback validates the state cookie
5. the service exchanges the GitHub code for a GitHub access token
6. the service fetches the GitHub user profile
7. the service upserts the Lighthouse user
8. the service generates a Lighthouse web bearer token
9. the service redirects the caller to the web client with the token in the URL fragment

### Bearer Token Storage

Bearer-token state is stored on the `users` row:

- `api_token_hash`
- `api_token_encrypted`
- `api_token_issued_at`
- `mcp_token_hash`
- `mcp_token_encrypted`
- `mcp_token_issued_at`

The plaintext token is:

- hashed for indexed lookup
- encrypted for verification and later rotation/revocation logic

### Request Authentication

For normal protected calls, both HTTP and MCP use:

```text
Authorization: Bearer <token>
```

The central auth logic lives in `services/mcp_client/src/mcp_client/utilities/auth.py`.

For HTTP:

- the HTTP wrapper resolves the caller before invoking the handler
- if the method accepts `auth`, the wrapper injects `AuthenticatedUser`
- the wrapper also stores the resolved user on `request.state.authenticated_user`

For MCP:

- the MCP wrapper resolves the caller from the underlying request headers
- if the method accepts `auth`, the wrapper injects `AuthenticatedUser`

This means handlers do not perform repeated auth checks themselves.

## Search and Retrieval Model

The search surface is owned by `SearchService` in `services/mcp_client/src/mcp_client/engine/search.py`.

### Main Entry Point: `get_code_context`

This is the intended main MCP entrypoint for coding agents that need non-local context for a task.

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
- normalizes some string inputs
- captures the request envelope
- returns a typed placeholder response with `status = "not_implemented"`

Intended future use:

- repository-aware retrieval for coding tasks
- search for architecture, conventions, invariants, and cross-file context
- ranked snippets or file suggestions for agent workflows

## User Repository Management

`UserService` owns lightweight repository registration and user-specific visibility preferences.

Exposed operations:

- HTTP `POST /v1/user/repos`
- HTTP `DELETE /v1/user/repos/{repo_id:path}`
- MCP `add_user_repo`
- MCP `remove_user_repo`

Behavior:

- repository references are normalized to `owner/repo`
- GitHub URLs and `owner/repo` input forms are accepted
- repositories are stored once globally in `repositories`
- public repositories are visible to everyone unless they hide them
- private repositories are visible only to users who currently have GitHub access
- create is idempotent for an existing repository record
- removing a repository hides it only for the requesting user
- re-adding a hidden repository clears that user's hide without creating a duplicate global row

This is currently metadata management only. It does not yet trigger retrieval or indexing logic.

## Current HTTP Surface

The current HTTP routes are:

### Public

- `GET /health`
- `GET /v1/auth/github`
- `GET /v1/auth/github/callback`

### Protected

- `POST /v1/auth/logout`
- `GET /v1/auth/me`
- `POST /v1/user/repos`
- `DELETE /v1/user/repos/{repo_id:path}`
- `POST /v1/search/code-context`

## Current MCP Surface

The current MCP tools are:

- `get_current_user`
- `add_user_repo`
- `remove_user_repo`
- `get_code_context`

All current MCP tools require authorization.

## Data Model

The Peewee models live in `services/mcp_client/src/mcp_client/models/auth.py`.

### `User`

Fields include:

- GitHub identity fields
- display metadata
- bearer-token fields
- timestamps

### `Repository`

Fields include:

- `github_repo_id`
- `repo_id`
- `repo_url`
- `display_name`
- `owner_login`
- `owner_type`
- `is_private`
- `added_at`

Repositories are global and unique. User-specific hiding is tracked separately.

### `UserHiddenRepository`

Fields include:

- `user_id`
- `repository_id`
- `hidden_at`

This table tracks which repositories a specific user has chosen to hide without removing the shared repository row.

### `Session`

`Session` still exists in the schema and model layer as a legacy table, even though the protected-route path now uses bearer tokens stored on `User`.

## Database Lifecycle

`packages/db/src/db/database.py` defines `DatabaseManager`.

It owns:

- the configured DSN
- the concrete Peewee `Database`
- the shared `DatabaseProxy`
- connection lifecycle helpers
- a `connection_context()` helper for thread-based query work

The app keeps a reference to this object on `app.database`.

Important implementation detail:

- some DB work currently runs inside `asyncio.to_thread(...)`
- those threaded sections use `app.database.connection_context()` so Peewee has a valid connection in the worker thread

## Configuration

The MCP service uses a typed settings model in `services/mcp_client/src/mcp_client/utilities/config/env.py`.

### Load Order

Settings are loaded in this order:

1. explicit init values
2. environment variables
3. `.env` values
4. file secret settings
5. SSM parameter payload

That means environment variables override the SSM payload field-by-field.

### SSM Support

If `MCP_CLIENT_SETTINGS_SSM_PARAMETER` (or legacy `LIGHTHOUSE_MCP_SETTINGS_SSM_PARAMETER`) is set, the service attempts to load one JSON object from AWS Systems Manager Parameter Store and use it as a settings source.

### Important Settings

- `DEBUG`
- `CORS_ALLOW_ORIGINS`
- `POSTGRES_DSN`
- `MCP_CLIENT_SETTINGS_SSM_PARAMETER` (legacy: `LIGHTHOUSE_MCP_SETTINGS_SSM_PARAMETER`)
- `AWS_REGION`
- `GITHUB_OAUTH_CLIENT_ID`
- `GITHUB_OAUTH_CLIENT_SECRET`
- `GITHUB_OAUTH_CALLBACK_URL`
- `SESSION_ENCRYPTION_KEY`
- `WEB_CLIENT_URL`
- `SESSION_TTL_HOURS`

## Error Model

The service uses a shared `RequestError` type for client-facing failures.

Purpose:

- raise one error shape from service code
- let HTTP wrappers translate it to HTTP status codes
- let MCP wrappers translate it into transport-friendly failures

`AuthorizationError` extends `RequestError` with a default `401` status.

## Logging and Runtime Introspection

The service uses shared logging helpers from `services/mcp_client/src/mcp_client/utilities/logging`.

At startup:

- HTTP routes are pretty-printed in a table
- MCP tools are pretty-printed in a table

This makes it easy to confirm which decorated handlers were actually discovered.

## Local Development

Current local setup from `services/mcp_client/README.md`:

1. create a virtual environment
2. install dependencies
3. copy `.env.example` to `.env`
4. run:

```shell
uvicorn mcp_client.main:app --reload --host 0.0.0.0 --port 8000 --env-file .env
```

## Current Limitations and Follow-Up Work

The most important gaps at the time of writing are:

- `get_code_context` is a validated placeholder and does not yet retrieve real context
- there is no search backend, ranking pipeline, or snippet retrieval implemented yet
- repository registration does not yet kick off indexing or retrieval preparation
- `Session` remains in the schema as legacy state
- tests and CI/CD coverage for the service still need to be expanded
- README and older MCP docs may still refer to pre-refactor structure and should be converged over time

## Design Principles for Future Work

When extending this service, keep these constraints in place:

- business logic should live on engine service objects, not in transport handlers
- auth should remain declarative and wrapper-driven, not repeated inside handlers
- new HTTP and MCP surfaces should be added through shared decorators
- search should remain the center of the MCP value proposition
- request and response contracts should stay typed, even when implementations are placeholders
- runtime docs should describe the current implementation, not the aspirational one
