# Pipeline Service Design

## Scope

The pipeline service is the execution plane.

It is responsible for:

- Running Temporal workers continuously
- Executing indexing workflows/activities
- Populating storage systems used by MCP (S3, Postgres, Milvus)
- Emitting indexing status and job progress (to be implemented)

## Current implementation layout

```text
pipeline/
  src/
    config.py
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

This aligns with:

- durable execution
- retry behavior
- lower cold-start latency for runtime indexing requests

## Current status

- Workflow/activity/worker skeletons are implemented.
- Activities are placeholders and do not yet perform real ingestion/indexing work.
- Persistence for `index_jobs` and `index_states` is not implemented yet.
- Connectors for GitHub/S3/Postgres/Milvus are not implemented yet.

## Next implementation items (Pipeline side)

- Replace activity stubs with real stage execution.
- Add data connectors and persistence repositories.
- Record stage transitions, progress, and failures per job.
- Implement benchmark snapshot ingestion mode (manual/on-release trigger path).
- Implement evaluation refresh wiring for pinned benchmark snapshots.
- Define deferred trigger paths for rolling scraped ingestion, synthetic refresh, and targeted reprocessing.
- Implement retry policies and failure classification.
- Add unit tests for activities/workflows.
- Add startup checks for required dependencies/config.
