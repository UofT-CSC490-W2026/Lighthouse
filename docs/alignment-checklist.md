# Lighthouse Design-Implementation Alignment Checklist

Assessment date: 2026-02-19

## Status Legend

- `ALIGNED`: implementation follows intended direction
- `PARTIAL`: direction is correct but key pieces are missing or inconsistent
- `GAP`: implementation materially diverges from intended direction

## Requirement Alignment Checklist

| Requirement | Intended direction | Current implementation status | Alignment | Notes |
| --- | --- | --- | --- | --- |
| Ingestion, cleaning, transformation pipeline | Temporal workflows execute `INGEST -> CLEAN -> TRANSFORM -> STORE` for online and offline modes | Implemented in workflow orchestration and activities | ALIGNED | `pipeline/src/workflows.py`, `pipeline/src/activities.py` |
| Data lake/warehouse design | S3 data lake + Postgres metadata + Milvus retrieval serving | S3 and Postgres are active; runtime chunk writes/reads are now wired through Milvus | ALIGNED | `pipeline/src/activities.py`, `pipeline/src/connectors/milvus.py`, `mcp/src/services/semantic_search.py`, `mcp/src/services/retrieval_backend.py` |
| Data schemas | Canonical index/control schemas and dataset schemas reflected in code + migrations | `index_jobs`, `index_states`, `dataset_instances`, `pipeline_runs`, `quality_metrics` exist, and iteration-1 `repo_snapshots` deferral is now explicit | ALIGNED | `pipeline/src/db_models.py`, `pipeline/alembic/versions/*`, `docs/dataset-pipeline-plan.md` |
| Pipeline diagrams and technology stack | Diagrams and listed technologies match runtime reality | Docs now reflect JSONL artifact flows and Python-native transform/validation stages used in code | ALIGNED | `docs/dataset-pipeline-plan.md`, `pipeline/src/activities.py`, `pipeline/requirements.in` |
| Schedules and use cases | Runtime event-driven; offline benchmark/manual; rolling incremental; evaluation refresh; deferred synthetic/reprocessing | Runtime, benchmark, rolling, and evaluation paths exist; synthetic and targeted reprocessing remain deferred | PARTIAL | `pipeline/src/workflows.py`, `pipeline/src/offline_trigger.py`, `pipeline/src/evaluation_refresh_trigger.py`, `docs/TODO.md` |
| Initial pipeline code | Initial working version of pipeline with tests | Implemented with passing unit coverage for activities/workflows and offline adapters | ALIGNED | `pipeline/tests/*` |
| Next-step roadmap for deferred features | Clear backlog for post-iteration features | Present and mostly explicit in roadmap and TODO docs | ALIGNED | `docs/ROADMAP.md`, `docs/TODO.md` |

## Directional Architecture Checklist

| Architecture direction | Current status | Alignment | Notes |
| --- | --- | --- | --- |
| MCP is read/control plane, pipeline is execution plane | Service boundary is respected in code layout and control flow | ALIGNED | `mcp/src/routes/*`, `pipeline/src/worker.py` |
| Route signatures are canonical MCP tool specs | Implemented as source of truth for tool exposure | ALIGNED | `mcp/src/routes/tool/*`, `mcp/src/server.py` |
| Index lifecycle contract (`NOT_FOUND/PENDING/READY/FAILED/STALE`) gates tools | Implemented and tested | ALIGNED | `mcp/src/routes/tool/common.py`, `mcp/tests/test_tool_index_gating.py` |
| Optional request-scoped GitHub credentials for private repos | Header extraction and end-to-end propagation into runtime workflow payloads are implemented; token remains optional | ALIGNED | `mcp/src/auth/request_auth.py`, `mcp/src/routes/public/index_control.py`, `mcp/src/routes/tool/common.py`, `mcp/src/clients/temporal.py`, `pipeline/src/workflows.py` |
| Retrieval-quality path (semantic/code graph/history/dependency) | Semantic and dependency retrieval should be backend-backed; remaining tool domains can be iterative | Semantic retrieval and dependency context now use Milvus runtime chunks; history/code-graph remain placeholder | PARTIAL | `mcp/src/services/semantic_search.py`, `mcp/src/services/dependencies.py`, `mcp/src/services/code_graph.py`, `mcp/src/services/history.py` |
| Mental model refresh and artifact persistence | Workflow/activity scaffolding exists; material artifact wiring is still deferred | PARTIAL | `pipeline/src/workflows.py`, `pipeline/src/activities.py`, `docs/TODO.md` |

## Concrete Alignment TODO (Priority-Ordered)

## P0: Close contract and direction gaps before claiming full alignment

- [x] Wire request-scoped GitHub token end-to-end: MCP request headers -> index-control start request -> Temporal workflow args -> pipeline ingest payload.
- [x] Keep token optional: public-repo indexing must succeed when no token is provided.
- [x] Add tests for token propagation and optional-token behavior (public/no-token and private/token paths).
- [x] Resolve schema mismatch for `repo_snapshots`: implement table + writes, or remove from canonical schema docs with explicit rationale.
- [x] Make a deliberate iteration-1 storage/tooling decision and codify it:
  - Path A: keep JSONL + Python-native transforms for iteration 1 and update all docs consistently.
  - Path B: implement Parquet + Polars/PyArrow/Pandera in offline stages and storage conventions.

## P1: Align retrieval execution with architecture intent

- [x] Implement Milvus write path for runtime transformed chunks in `store_activity`.
- [x] Implement minimal semantic retrieval in MCP (`get_context_for_change`) backed by Milvus/Postgres.
- [x] Replace at least one placeholder domain service with a real implementation (`history`, `dependencies`, or `code_graph`).
- [x] Add one end-to-end integration test: runtime index completes -> tool query returns non-empty retrieval result.

## P2: Align deferred pipeline evolution with documented operating model

- [ ] Add synthetic dataset workflow skeleton with explicit disabled-by-default schedule.
- [ ] Add targeted reprocessing trigger contract and workflow entrypoint for correction/schema events.
- [ ] Add `MentalModelWorkflow` artifact persistence contract and output schema.
- [ ] Add a small architecture note documenting what remains intentionally deferred after MVP.
