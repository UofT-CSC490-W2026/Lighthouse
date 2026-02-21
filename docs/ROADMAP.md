# Lighthouse Roadmap

## Current Direction

Architecture is now explicitly split into:

- MCP service (`mcp/`) as read/control plane
- Pipeline service (`pipeline/`) as execution plane

## Phase 1: Skeleton Alignment

1. MCP route signatures defined and exposed via FastAPI-MCP.
2. MCP service-layer placeholders created.
3. Pipeline Temporal worker/workflow/activity skeleton created.
4. Remove static MCP tool registry (`ALL_TOOLS`) and treat route signatures as canonical.

## Phase 2: Shared Contract and State

1. Implement canonical indexing contract from `docs/indexing-contract.md`.
2. Add `index_jobs` and `index_states` persistence schema.
3. Implement `IndexStatus`-aware MCP responses.
4. Implement idempotent workflow start semantics per `(repo_id, ref)`.

## Phase 3: MCP Control Plane

1. Add Temporal client wrapper in MCP.
2. Add index control endpoints:
   - start job
   - get job status
   - get repo state
   - retry
3. Add centralized error handling and response envelopes.

## Phase 4: Pipeline Execution Plane

1. Replace activity stubs with real stage implementations.
2. Implement connectors for GitHub, S3, Postgres, Milvus.
3. Persist stage progress, failures, and final index state.
4. Add retry policies, startup checks, and structured logs.
5. Implement offline data operation policy:
   - immutable, version-pinned benchmark snapshot ingestion
   - daily incremental ingestion for rolling scraped sources
   - weekly synthetic dataset refresh
   - targeted reprocessing paths for schema/correction events

## Phase 5: Retrieval Quality

1. Implement real code graph/history/dependency queries in MCP services.
2. Implement semantic retrieval integration and ranking fusion.
3. Implement mental model hydration and query hooks.
4. Add regression and quality tests for all tool endpoints.

## Phase 6: Evaluation

1. Build evaluation harness for fail-to-pass delta and regression rate.
2. Pin stable benchmark snapshots for baseline comparability across runs.
3. Run baseline comparisons (agent-only vs MCP-enabled).
4. Iterate on ranking and context selection quality.
