# MCP Service Design

## Scope

The MCP service is the read/control plane.

It is responsible for:

- Exposing MCP tools via FastAPI-MCP
- Returning repository context to agents
- Triggering and observing indexing workflows
- Respecting pipeline data-state and freshness semantics; offline dataset recompute policy remains pipeline-owned

It is not responsible for executing pipeline ingestion logic.

## Current implementation layout

```text
mcp/
  src/
    server.py
    routes/
      public/
        health.py
      tool/
        context.py
        code_graph.py
        history.py
        conventions.py
        dependencies.py
    services/
      context.py
      code_graph.py
      history.py
      conventions.py
      dependencies.py
      semantic_search.py
      ranking.py
      mental_model.py
    types/
      tools.py
    utils/
      config/
      logger/
```

## Canonical tool API

Tool routes are defined by FastAPI signatures under `mcp/src/routes/tool/`:

- `POST /tools/get_context_for_change`
- `POST /tools/get_callers`
- `POST /tools/get_contract`
- `POST /tools/get_history`
- `POST /tools/get_conventions`
- `POST /tools/get_dependency_context`

These route signatures are the source of truth for MCP exposure.

## Current status

- Tool routes exist and are wired through FastAPI-MCP.
- Service-layer modules exist; index-control and gating behavior are implemented while retrieval backends remain placeholder.
- Health endpoint exists (`GET /health`).
- Temporal control endpoints are implemented (`POST /v1/index/jobs`, `GET /v1/index/jobs/{job_id}`, `GET /v1/index/repos/{repo_id}/state`, `POST /v1/index/repos/{repo_id}/retry`).
- Tool routes now enforce index-state gating (`NOT_FOUND`, `PENDING`, `READY`, `FAILED`, `STALE`) with a shared envelope.
- MCP can accept optional request-scoped GitHub token headers from MCP clients (`Authorization: Bearer ...`, fallback `X-GitHub-Token`) for private-repo-capable flows.

## Next implementation items (MCP side)

- Add smoke/integration tests for index-state gating and one tool call per state.
- Add per-repository multi-token routing strategy for private repositories.
- Replace placeholder retrieval implementations with real backends (code graph, history, dependency context, semantic ranking).
