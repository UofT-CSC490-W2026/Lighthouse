# Web Service

`services/web` is a small React/Vite frontend used primarily as an internal debugging console for Lighthouse. It is not the main product surface. Its job is to make a few backend workflows easy to validate manually:

- GitHub sign-in and API token handoff
- Repository registration and branch indexing status
- MCP token generation for external clients such as Cursor
- Indexed code search against repositories already known to Lighthouse

## Architecture

The frontend is a client-side React 19 application built with Vite and TypeScript.

```text
services/web/
├── src/
│   ├── pages/          # Route-level screens
│   ├── components/     # Reusable UI building blocks
│   ├── lib/
│   │   ├── api.ts      # Authenticated fetch wrapper and shared API types
│   │   ├── auth.ts     # localStorage token persistence
│   │   ├── hooks.ts    # Auth-aware data hooks
│   │   └── branches.ts # Branch input normalization
│   ├── App.tsx         # Router
│   └── main.tsx        # App bootstrap
├── package.json
└── vite.config.ts
```

### Routes

The app currently exposes these routes:

| Route | Purpose |
|---|---|
| `/login` | Starts GitHub auth via the backend |
| `/auth/callback` | Reads the returned API token from the URL hash and stores it locally |
| `/dashboard` | Main debugging view for repos and MCP token management |
| `/dashboard/add-repo` | Form for registering a repository and optional extra branches |
| `/dashboard/search` | Manual search UI for indexed code and wiki snippets |

Unknown routes redirect to `/dashboard`.

## Authentication Model

The web app uses a Lighthouse API token stored in browser `localStorage` under `MCP_SERVER_TOKEN`.

1. `/login` sends the user to the backend GitHub auth endpoint.
2. After GitHub auth completes, the backend redirects back to `/auth/callback#token=...`.
3. `AuthCallback` extracts the token from the hash fragment and stores it in `localStorage`.
4. Authenticated screens call `useUser()`, which fetches `/v1/auth/me`.
5. If the token is missing or rejected, the frontend clears it and sends the user back to `/login`.

This token is separate from the long-lived MCP token shown on the dashboard. Signing out clears the web token only.

## Main Debugging Workflows

### 1. Sign in and confirm auth health

Use `/login` to start the GitHub flow. A successful sign-in lands on `/dashboard`, where `useUser()` confirms the session by calling `/v1/auth/me`.

This flow is useful for validating:

- GitHub OAuth wiring
- frontend redirect behavior
- token persistence in the browser
- backend auth/session health

### 2. Inspect repository indexing state

The dashboard is the main operations screen. It shows:

- the list of repositories attached to the current user
- overall indexing state for each repository
- per-branch indexing status
- actions to remove a repo or request indexing for more branches

`RepoList` polls `/v1/user/repos` every 5 seconds so indexing progress is visible without a manual refresh. This makes the UI useful for watching branch state move through `PENDING`, `INDEXING`, `INDEXED`, or `FAILED`.

### 3. Add a repository for indexing

`/dashboard/add-repo` accepts either a full GitHub URL or `owner/repo`. The default branch is always indexed. The form can also include extra branches as a comma-separated list.

This is primarily a debugging and setup action for testing downstream search behavior, not a full repository management workflow.

### 4. Add more branches later

Each repository card includes an “Add branches” dialog. Branch names are entered as a comma-separated list and normalized client-side to:

- trim whitespace
- drop empty entries
- deduplicate repeated names

This is useful when debugging branch-specific indexing or checking whether search results differ across branches.

### 5. Manage the long-lived MCP token

The dashboard includes an expandable MCP token panel. It can:

- fetch the current token state
- generate or refresh a token
- revoke a token
- copy the raw token
- copy a ready-to-merge Cursor `mcp.json` example

This panel exists to support local integration testing with MCP clients. The token it manages does not automatically expire and does not control the current browser session.

### 6. Run manual indexed-code searches

`/dashboard/search` is a debugging surface for the search backend. It allows the operator to:

- choose a repository
- choose an indexed branch
- enter a natural-language query
- optionally narrow by file path

The results view shows:

- backend status and message
- the selected repository and branch
- returned snippet count
- code snippets with file path and line numbers
- wiki snippets when returned by the backend
- follow-up suggestions emitted by the API

This page is intended for manually inspecting search quality and backend behavior, not for polished end-user discovery workflows.

## Backend Integration

The frontend talks to the backend through `apiFetch()` in `src/lib/api.ts`. `VITE_MCP_URL` is used as the base URL. If unset, requests are made relative to the current origin.

### Endpoints currently used

| Endpoint | Method | Used for |
|---|---|---|
| `/v1/auth/github` | `GET` via browser navigation | Start GitHub auth |
| `/v1/auth/me` | `GET` | Resolve the current signed-in user |
| `/v1/auth/logout` | `POST` | Best-effort logout before clearing local auth state |
| `/v1/auth/mcp-token` | `GET` | Fetch MCP token state |
| `/v1/auth/mcp-token` | `POST` | Generate or rotate MCP token |
| `/v1/auth/mcp-token` | `DELETE` | Revoke MCP token |
| `/v1/user/repos` | `GET` | List repositories and branch indexing status |
| `/v1/user/repos` | `POST` | Add a repository for indexing |
| `/v1/user/repos/:repoId` | `DELETE` | Remove a repository from the user’s list |
| `/v1/user/repos/:repoId/branches` | `POST` | Add branches for indexing |
| `/v1/search/search-code` | `POST` | Run code-context search |

### Error handling

`apiFetch()` centralizes request behavior:

- adds `Authorization: Bearer <token>` when a web token is present
- serializes JSON request bodies
- clears the stored web token on `401`
- extracts useful backend error text from JSON or plain-text responses

The UI generally surfaces backend errors directly. That is intentional for a debugging tool because the raw detail is often more useful than a polished generic error message.

## Important Screens and Components

### Pages

- `Login.tsx`: starts backend auth and shows login errors
- `AuthCallback.tsx`: completes token handoff from the URL hash
- `Dashboard.tsx`: repo and MCP token overview
- `AddRepo.tsx`: add-repository form wrapper
- `Search.tsx`: manual search runner and result viewer

### Components

- `Navbar`: app navigation and sign-out action
- `MCPTokenPanel`: token inspection and client-config help
- `RepoList`: repository polling and empty/error states
- `RepoCard`: repo status, branch status, removal, and branch-add flow
- `SnippetCard`: syntax-highlighted code results with line numbers
- `WikiCard`: wiki result rendering with fenced-code block parsing
- `StatusBadge`: visual mapping for branch/index state

## Configuration and Local Development

### Environment

| Variable | Required | Description |
|---|---|---|
| `VITE_MCP_URL` | Usually | Base URL for backend API requests and GitHub auth start URL |

Example:

```bash
VITE_MCP_URL=http://localhost:8000
```

### Commands

```bash
npm --prefix services/web run dev
npm --prefix services/web run build
```

The frontend assumes the backend is already running and reachable at `VITE_MCP_URL`.

## Maintenance Notes

- `useUser()` is the main auth gate for protected screens.
- SWR is used for data fetching. Repository polling is intentional because indexing status changes asynchronously.
- Branch input parsing is intentionally minimal and lives in `src/lib/branches.ts`.
- Search result rendering supports both code and wiki snippets because the backend response can contain either.
- The UI currently has no dedicated frontend test suite configured in this repository.

## Troubleshooting

### Redirect loop back to `/login`

Usually means the stored web token is missing, expired, or rejected by `/v1/auth/me`. The frontend clears invalid tokens automatically on `401`.

### Auth completed but the UI reports a missing token

`/auth/callback` expects `#token=...` in the URL hash. If the backend redirects without that fragment, login cannot complete.

### Repository list stays empty

Check whether the user actually has repositories registered in `/v1/user/repos`, and confirm the request is going to the expected backend via `VITE_MCP_URL`.

### Branch search results are missing

The selected branch may not be indexed yet. The dashboard’s branch badges are the quickest way to confirm whether a branch is still pending, indexing, failed, or ready.

### Search errors look raw or overly detailed

That is expected. The UI intentionally exposes backend error detail because this surface is meant for debugging service behavior.

### MCP token actions do not affect the current login session

This is expected. The dashboard’s MCP token is a separate long-lived credential for external MCP clients, not the browser auth token used by the web app itself.
