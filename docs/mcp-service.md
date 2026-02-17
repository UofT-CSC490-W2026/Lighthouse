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
- Service-layer modules exist but are placeholders.
- Health endpoint exists (`GET /health`).
- Temporal control endpoints are not implemented yet.
- Index-state gating (`NOT_FOUND`, `PENDING`, `READY`, `FAILED`, `STALE`) is not implemented yet.

## Next implementation items (MCP side)

- Add Temporal client wrapper under `mcp/src`.
- Add index control endpoints (start job, get job, get repo state, retry).
- Add state-aware tool response behavior.
- Add shared response envelope with index metadata.
- Align config loading with Parameter Store + `.env` fallback.
