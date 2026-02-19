# Pipeline Service Design

## Scope

The pipeline service is the execution plane.

It is responsible for:

- Running Temporal workers continuously
- Executing indexing workflows/activities
- Populating storage systems used by MCP (S3, Postgres, Milvus)
- Emitting indexing status and job progress
- Exposing HTTP liveness/readiness endpoints for orchestration health checks

## Current implementation layout

```text
pipeline/
  src/
    config.py
    server.py
    state.py
    activities.py
    workflows.py
    worker.py
```

## Temporal model

### Workflows

- `RuntimeIndexWorkflow`
- `OfflineDatasetWorkflow`
- `MentalModelWorkflow`

### Activities

- `ingest_activity`
- `clean_activity`
- `transform_activity`
- `store_activity`
- `mental_model_activity`

### Task queues

- `runtime-indexing`
- `offline-datasets`
- `mental-model`

## Offline data policy

- Iteration 1: external benchmark snapshots (for example, fixed SWE-bench releases) are ingested once, version-pinned, and treated as immutable.
- Iteration 1: full historical recompute is not the default; rerun benchmark ingestion only for explicit correction events.
- Post-iteration 1: rolling scraped sources (for example, issue->PR->diff chains) should be processed via incremental append/upsert runs.
- Post-iteration 1: synthetic datasets should refresh on cadence and on demand when generator logic/scoring/schema changes.

## Target cadence (iteration 1)

| Workflow | Cadence | Use case |
| --- | --- | --- |
| `RuntimeIndexWorkflow` | Event-driven | On-demand repo indexing for MCP tool readiness |
| `OfflineDatasetWorkflow` (benchmark snapshots) | Manual or on new benchmark release | Import and normalize immutable benchmark snapshots |
| Evaluation refresh | Monthly or on snapshot update | Refresh fail-to-pass and regression trends |

## Deferred cadence (post-iteration 1)

| Workflow | Cadence | Use case |
| --- | --- | --- |
| `OfflineDatasetWorkflow` (rolling scraped sources) | Daily | Ingest newly available issue/PR/fix chains incrementally |
| `OfflineDatasetWorkflow` (synthetic refresh) | Weekly | Regenerate synthetic tasks/features |
| `OfflineDatasetWorkflow` (targeted reprocessing) | Event-driven/manual | Repair affected partitions after schema/correction events |

## Worker model

Workers are designed to run as long-lived processes and poll Temporal task queues.

Deployment entrypoint uses `uvicorn` with a lightweight FastAPI app (`src.server:app`) that:

- exposes `/health` and `/ready` for ECS/service health checks
- starts worker loops in-process during app lifespan startup
- keeps execution semantics queue-driven through Temporal workers

This aligns with:

- durable execution
- retry behavior
- lower cold-start latency for runtime indexing requests

## Current status

- Workflow/activity/worker skeletons are implemented.
- Runtime and offline activity implementations are in place for iteration-1 scope.
- Persistence for `index_jobs` and `index_states` is implemented.
- Connectors for GitHub/S3/Postgres/Milvus are implemented.
- Monthly evaluation refresh workflow wiring is implemented for pinned benchmark snapshots.
- Per-run metrics persistence is implemented via `pipeline_runs` (`records_in`, `records_out`, `failure_count`, `duration_ms`).
- Baseline evaluation wiring is implemented for fail-to-pass and regression-rate tracking (`quality_metrics`).
- Rolling issue->PR->diff offline ingestion is implemented with incremental controls (`watermark_start`, `watermark_end`, `max_records`, `source_cursor`) and deterministic chain dedupe.

## Next implementation items (Pipeline side)

- Add synthetic dataset refresh workflow schedule and generator version tracking.
- Define targeted reprocessing policy and trigger paths for schema/correction events.
- Add mental-model refresh scheduling and artifact persistence wiring.
- Add `context_labels` export pipeline with confidence metadata.
- Train and integrate learned retrieval-ranking over gold datasets.
- Add data quality scorecards, drift alerts, and freshness SLO gating.
