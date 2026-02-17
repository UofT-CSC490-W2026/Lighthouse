# Indexing Contract (MCP <-> Pipeline)

## Purpose

Define the canonical control/state contract between the MCP service and the pipeline worker service.

This contract governs runtime indexing control/state for `(repo_id, ref)`.
Offline dataset scheduling and recompute policy are defined in `docs/dataset-pipeline-plan.md`.

## Canonical Enums

### `IndexStatus`

- `NOT_FOUND`: no index exists for `(repo_id, ref)`
- `PENDING`: an indexing job is active
- `READY`: index is usable
- `FAILED`: last indexing attempt failed
- `STALE`: index exists but is older than freshness policy

### `IndexStage`

- `INGEST`
- `CLEAN`
- `TRANSFORM`
- `STORE`
- `MENTAL_MODEL`

## Canonical Identifiers

- `repo_id`: stable service identifier for target repo
- `ref`: branch/tag context (default `main`)
- `snapshot_sha`: commit SHA represented by READY/STALE index
- `job_id`: indexing job identifier
- `workflow_id`: Temporal workflow identifier

## Idempotency Rule

Default runtime workflow id:

- `runtime-index:{repo_id}:{ref}`

Unless `force_reindex=true`, starting a new runtime index request for the same `(repo_id, ref)` should reuse or return the active job.

## Control API shapes

### Start job

`POST /v1/index/jobs`

Request:

```json
{
  "repo_id": "org/repo",
  "repo_url": "https://github.com/org/repo",
  "ref": "main",
  "trigger": "mcp_auto",
  "requested_by": "get_context_for_change",
  "force_reindex": false
}
```

Response (`202`):

```json
{
  "job_id": "idx_123",
  "workflow_id": "runtime-index:org/repo:main",
  "status": "PENDING"
}
```

### Get job status

`GET /v1/index/jobs/{job_id}`

Response:

```json
{
  "job_id": "idx_123",
  "repo_id": "org/repo",
  "ref": "main",
  "status": "PENDING",
  "stage": "TRANSFORM",
  "progress_pct": 62,
  "workflow_id": "runtime-index:org/repo:main",
  "error_code": null,
  "error_message": null
}
```

### Get repo index state

`GET /v1/index/repos/{repo_id}/state?ref=main`

Response:

```json
{
  "repo_id": "org/repo",
  "ref": "main",
  "status": "READY",
  "snapshot_sha": "abc123",
  "active_job_id": null
}
```

### Retry

`POST /v1/index/repos/{repo_id}/retry?ref=main`

Response: same shape as start job (`202`).

## MCP tool behavior by index state

- `READY`: serve tool result
- `STALE`: serve result + staleness metadata
- `PENDING`: return pending response with `job_id`
- `NOT_FOUND`: optionally auto-start job, return pending response
- `FAILED`: return failure metadata + retry hint

## Tool response envelope (target)

```json
{
  "index": {
    "status": "READY",
    "repo_id": "org/repo",
    "ref": "main",
    "snapshot_sha": "abc123",
    "job_id": null
  },
  "result": {},
  "message": null
}
```
