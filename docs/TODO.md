# Lighthouse Implementation TODO

## Alignment Priority Queue (Current)

Reference checklist: `docs/alignment-checklist.md`

### P0: Contract and architecture alignment

- [x] Wire optional request-scoped GitHub token end-to-end (`mcp` header extraction -> index-control request -> Temporal args -> pipeline ingest payload).
- [x] Add tests for token behavior:
  - no token (public repo) remains valid
  - token present (private repo) is propagated to ingest connector
- [x] Resolve `repo_snapshots` schema drift:
  - implement table + persistence wiring, or
  - remove from canonical dataset schema docs with explicit iteration-1 rationale.
- [x] Choose and lock iteration-1 data format/tooling direction:
  - keep JSONL + native transforms (and make docs consistent), or
  - implement Parquet + Polars/PyArrow/Pandera in code.

### P1: Retrieval path alignment

- [x] Add runtime Milvus write path in `pipeline/src/activities.py` during `STORE`.
- [x] Implement minimal Milvus-backed semantic retrieval in `mcp/src/services/semantic_search.py`.
- [x] Replace one placeholder MCP domain service (`history`, `dependencies`, or `code_graph`) with a real backend path.
- [x] Add one e2e integration test: runtime index success -> MCP tool returns non-empty result.

### P2: Deferred pipeline alignment (explicitly post-MVP)

- [ ] Revisit and re-approve iteration-1 storage/tooling direction with collaborator sign-off (`JSONL + native transforms` vs `Parquet + Polars/PyArrow/Pandera`) before scale-up work.
- [ ] Add synthetic dataset refresh workflow skeleton with disabled-by-default scheduling.
- [ ] Add targeted reprocessing trigger contract + workflow entrypoint.
- [ ] Add `MentalModelWorkflow` artifact persistence contract/output schema.

## Shared (MCP + Pipeline)

- [x] Document canonical indexing contract in `docs/indexing-contract.md`.
- [x] Implement shared contract models in code for: `repo_id`, `ref`, `snapshot_sha`, `status`, `stage`, `progress_pct`, `job_id`, `workflow_id`, `error_code`, `error_message`.
- [x] Implement canonical enums in code for `IndexStatus` (`NOT_FOUND`, `PENDING`, `READY`, `FAILED`, `STALE`) and stage names.
- [x] Implement workflow ID/idempotency convention in code (for example: `runtime-index:{repo_id}:{ref}`).
- [x] Implement API payload models for `start job`, `get job`, `get repo state`, and `retry job`.
- [x] Decide shared-model location and refactor to single shared module: `shared/src/indexing.py`.
- [x] Add a configuration provider abstraction and pull runtime settings/secrets (endpoints, tokens, DSNs, queue names) from AWS Parameter Store, with local development config passed via process environment (for example, `--env-file`).

## Pipeline Service

- [x] Implement real activities in `pipeline/src/activities.py` (replace stubs with ingest/clean/transform/store logic for runtime + benchmark workflows; keep `mental_model_activity` deferred).
- [x] Add data connectors (Postgres, Milvus, S3, GitHub) under `pipeline/src`.
- [x] Add persistence layer for `index_jobs` and `index_states` writes/updates.
- [x] Update `pipeline/src/workflows.py` to write stage transitions and progress at each step.
- [x] Add Temporal retries/timeouts/backoff policies per activity.
- [x] Add cancellation handling and failure classification (`retryable` vs `terminal`).
- [x] Add worker startup validation in `pipeline/src/worker.py` (config and backend connectivity checks).
- [x] Add structured logs + correlation IDs (`repo_id`, `workflow_id`, `job_id`).
- [x] Add unit tests for each activity and workflow happy/failure paths in `pipeline/tests`.
- [x] Expose pipeline HTTP liveness/readiness endpoints (`/health`, `/ready`) and run worker loops under `uvicorn` for ECS task health checks.

## Dataset Pipeline (Iteration 1 Scope)

- [x] Publish dataset pipeline design doc: `docs/dataset-pipeline-plan.md`.
- [x] Draft report section: `docs/report-data-processing-pipeline.md`.
- [x] Define bronze/silver/gold S3 partitioning conventions and run manifest schema.
- [x] Implement offline source adapter for SWE-bench benchmark snapshots (version-pinned, immutable).
- [x] Add cleaning and normalization layer with deterministic dedupe rules.
- [x] Add schema validation and invalid-row quarantine behavior for offline runs.
- [x] Implement iteration-1 gold dataset export tables for `dataset_instances`.
- [x] Add benchmark snapshot ingestion trigger path (manual or new snapshot release).
- [x] Add monthly evaluation refresh job wiring against pinned benchmark snapshots.
- [x] Persist per-run metrics (`records_in`, `records_out`, failure counts, duration).
- [x] Add baseline evaluation job wiring for fail-to-pass and regression-rate tracking.

## Dataset Pipeline (Post-Iteration-1 Deferred)

- [x] Add rolling scraped offline pipeline for incremental issue->PR->diff ingestion.
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

## MVP Refactor/Cleanup (Pre-Scale)

### Phase 0: Safety rails before structural changes

- [x] Publish design/implementation alignment checklist and priority queue in `docs/alignment-checklist.md` + `docs/TODO.md`.
- [x] Complete Alignment Priority Queue `P0` items before structural refactor work.
- [x] Complete Alignment Priority Queue `P1` items, or explicitly defer each with rationale before structural refactor work.
- [ ] Freeze behavior with snapshot tests around existing API contracts:
  - MCP public index-control endpoints (`/v1/index/...`)
  - MCP tool envelopes (`index`, `result`, `message`, `retry`)
  - Pipeline workflow outputs and persisted status transitions
- [x] Add a refactor gate in CI: run formatting + both test suites (`mcp`, `pipeline`) on every refactor PR.
- [ ] Document non-goals for the refactor (no feature expansion, no schema changes unless explicitly scoped).

### Phase 1: Pipeline decomposition and DRY orchestration

- [ ] Split `pipeline/src/activities.py` into focused modules while preserving public activity names:
  - `pipeline/src/activities/runtime.py`
  - `pipeline/src/activities/offline.py`
  - `pipeline/src/activities/evaluation.py`
  - `pipeline/src/activities/persistence.py`
  - `pipeline/src/activities/common.py`
- [ ] Move pure transformation/normalization helpers into dedicated libraries:
  - `pipeline/src/runtime_processing/*` for chunking/source normalization
  - `pipeline/src/offline_processing/*` for clean/dedupe/schema normalization
- [ ] Split `pipeline/src/workflows.py` into per-workflow modules and shared orchestration utilities:
  - `pipeline/src/workflows/runtime.py`
  - `pipeline/src/workflows/offline.py`
  - `pipeline/src/workflows/evaluation.py`
  - `pipeline/src/workflows/mental_model.py`
  - `pipeline/src/workflows/common.py`
- [ ] Introduce shared workflow runner helpers for repeated patterns:
  - stage execution loops
  - error classification + persistence
  - run-metrics best-effort persistence
  - structured workflow logging/correlation
- [ ] Keep backward-compatible import surface via `pipeline/src/activities/__init__.py` and `pipeline/src/workflows/__init__.py`.

### Phase 2: Explicit interfaces (ports/adapters) and service boundaries

- [ ] Define abstract interfaces (ABC/Protocol) for offline sources:
  - common snapshot contract (`records`, source metadata, optional incremental metadata)
  - dataset-specific adapter implementations (`swebench`, `issue_pr_diff`)
- [ ] Introduce an offline adapter registry keyed by dataset name aliases (replace branching in ingest path).
- [ ] Define interfaces for storage/persistence dependencies used in activities:
  - artifact store
  - dataset export writer
  - quality metrics writer
- [ ] Define Temporal orchestration interfaces in `pipeline` and `mcp` to isolate client-specific logic.

### Phase 3: MCP route/service cleanup and dependency injection

- [ ] Replace service-locator style globals in `mcp/src/services/__init__.py` with explicit FastAPI dependency providers.
- [ ] Add one reusable tool-execution wrapper to eliminate repetitive route logic:
  - gate request by index state
  - execute tool handler when allowed
  - return canonical response envelope
- [ ] Refactor tool route modules to thin endpoint declarations only.
- [ ] Split `mcp/src/types/tools.py` into domain-focused schema modules:
  - `types/tools/context.py`
  - `types/tools/code_graph.py`
  - `types/tools/history.py`
  - `types/tools/conventions.py`
  - `types/tools/dependencies.py`
  - shared envelope module
- [ ] Remove wildcard exports from `mcp/src/utils/__init__.py` and switch to explicit exports.

### Phase 4: Data-access unification and ORM ergonomics

- [ ] Unify MCP read persistence with pipeline persistence style:
  - replace raw `asyncpg` SQL in MCP repository with SQLAlchemy async repository layer
  - reuse shared SQL model contracts where appropriate
- [ ] Keep Alembic as migration source of truth during unification.
- [ ] After unification, run an ORM ergonomics spike and decide:
  - stay on SQLAlchemy with repository/query helpers, or
  - migrate selected areas to SQLModel
- [ ] If ORM migration is approved, create a dedicated migration plan with rollback checkpoints.

### Phase 5: Config/logging consistency and operational polish

- [ ] Create shared base settings primitives for MCP + pipeline to remove duplicated config fields.
- [ ] Standardize logger setup across services (single formatter policy, consistent correlation fields).
- [ ] Ensure startup validation patterns are consistent across MCP and pipeline.
- [ ] Align error taxonomy and mapping strategy between MCP route layer and pipeline service layer.

### Phase 6: Verification, docs, and rollout

- [ ] Add architecture notes describing new module boundaries and dependency direction rules.
- [ ] Add import-boundary checks to prevent monolith files from re-emerging.
- [ ] Add/expand type-checking and linting (for example: mypy + ruff) with incremental enforcement.
- [ ] Execute staged refactor PRs:
  - PR1 pipeline module split (no behavior change)
  - PR2 MCP DI + route wrapper consolidation
  - PR3 persistence unification
  - PR4 config/logging consistency + docs
- [ ] Require green test matrix after each PR (`pipeline` + `mcp`) before merging.

## Suggested Build Order

1. Shared contract models and API shapes.
2. Pipeline persistence and workflow stage/state updates.
3. MCP index-control endpoints and Temporal client.
4. Runtime activity implementations with retries, logging, and tests.
5. Offline benchmark snapshot ingestion + monthly evaluation refresh wiring.
6. Deferred post-iteration pipelines (rolling scraped, synthetic, targeted reprocessing, mental model).
