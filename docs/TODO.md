# Lighthouse Implementation TODO

## Shared (MCP + Pipeline)

- [x] Document canonical indexing contract in `docs/indexing-contract.md`.
- [x] Implement shared contract models in code for: `repo_id`, `ref`, `snapshot_sha`, `status`, `stage`, `progress_pct`, `job_id`, `workflow_id`, `error_code`, `error_message`.
- [x] Implement canonical enums in code for `IndexStatus` (`NOT_FOUND`, `PENDING`, `READY`, `FAILED`, `STALE`) and stage names.
- [x] Implement workflow ID/idempotency convention in code (for example: `runtime-index:{repo_id}:{ref}`).
- [x] Implement API payload models for `start job`, `get job`, `get repo state`, and `retry job`.
- [x] Decide shared-model location and refactor to single shared module: `shared/src/indexing.py`.
- [x] Add a configuration provider abstraction and pull runtime settings/secrets (endpoints, tokens, DSNs, queue names) from AWS Parameter Store, with local development config passed via process environment (for example, `--env-file`).

## Pipeline Service

- [ ] Implement real activities in `pipeline/src/activities.py` (replace stubs with ingest/clean/transform/store logic for runtime + benchmark workflows; keep `mental_model_activity` deferred).
- [ ] Add data connectors (Postgres, Milvus, S3, GitHub) under `pipeline/src`.
- [x] Add persistence layer for `index_jobs` and `index_states` writes/updates.
- [x] Update `pipeline/src/workflows.py` to write stage transitions and progress at each step.
- [ ] Add Temporal retries/timeouts/backoff policies per activity.
- [ ] Add cancellation handling and failure classification (`retryable` vs `terminal`).
- [ ] Add worker startup validation in `pipeline/src/worker.py` (config and backend connectivity checks).
- [ ] Add structured logs + correlation IDs (`repo_id`, `workflow_id`, `job_id`).
- [ ] Add unit tests for each activity and workflow happy/failure paths in `pipeline/tests`.

## Dataset Pipeline (Iteration 1 Scope)

- [x] Publish dataset pipeline design doc: `docs/dataset-pipeline-plan.md`.
- [x] Draft report section: `docs/report-data-processing-pipeline.md`.
- [ ] Define bronze/silver/gold S3 partitioning conventions and run manifest schema.
- [ ] Implement offline source adapter for SWE-bench benchmark snapshots (version-pinned, immutable).
- [ ] Add cleaning and normalization layer with deterministic dedupe rules.
- [ ] Add schema validation and invalid-row quarantine behavior for offline runs.
- [ ] Implement iteration-1 gold dataset export tables for `dataset_instances`.
- [ ] Add benchmark snapshot ingestion trigger path (manual or new snapshot release).
- [ ] Add monthly evaluation refresh job wiring against pinned benchmark snapshots.
- [ ] Persist per-run metrics (`records_in`, `records_out`, failure counts, duration).
- [ ] Add baseline evaluation job wiring for fail-to-pass and regression-rate tracking.

## Dataset Pipeline (Post-Iteration-1 Deferred)

- [ ] Add rolling scraped offline pipeline for incremental issue->PR->diff ingestion.
- [ ] Add synthetic dataset refresh workflow schedule and generator version tracking.
- [ ] Define targeted reprocessing policy and trigger paths for schema/correction events.
- [ ] Add `MentalModelWorkflow` refresh scheduling and artifact persistence wiring.
- [ ] Add `context_labels` export pipeline with confidence metadata.
- [ ] Train and integrate a learned retrieval-ranking layer over gold datasets.
- [ ] Add data quality scorecards, drift alerts, and freshness SLO gating.

## MCP Service

- [x] Add Temporal client wrapper under `mcp/src` (connect/start/query workflow).
- [x] Add index-control service (start job, poll status, fetch repo readiness).
- [x] Add MCP-facing endpoints for index control (`POST start`, `GET job`, `GET repo state`, `POST retry`).
- [x] Update tool route handlers in `mcp/src/routes/tool` to gate by index state before serving data.
- [x] Implement tool behavior by state: `READY` serve data, `PENDING` return pending payload, `NOT_FOUND` optionally auto-trigger, `FAILED` return retry guidance, `STALE` serve with stale flag.
- [x] Add common response envelope for tools including index metadata.
- [x] Accept optional request-scoped GitHub token headers from MCP clients (`Authorization`/`X-GitHub-Token`) without requiring tokens for public-repo indexing flows.
- [ ] Add per-repository multi-token routing support for private repos (deferred).
- [x] Add centralized error mapping/handlers (validation, backend unavailable, workflow errors).
- [x] Add smoke/integration tests in `mcp/tests` for index-state gating and one tool call per state.

## Suggested Build Order

1. Shared contract models and API shapes.
2. Pipeline persistence and workflow stage/state updates.
3. MCP index-control endpoints and Temporal client.
4. Runtime activity implementations with retries, logging, and tests.
5. Offline benchmark snapshot ingestion + monthly evaluation refresh wiring.
6. Deferred post-iteration pipelines (rolling scraped, synthetic, targeted reprocessing, mental model).
