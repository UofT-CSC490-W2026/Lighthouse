# Lighthouse Evaluation Framework

This document is the canonical guide for the evaluation framework implemented
under `evaluation/`.

A modular evaluation framework for measuring whether retrieval-augmented context improves LLM code generation. Designed to answer the question: *does the context Lighthouse surfaces actually help coding agents complete tasks?*

## Table of Contents

- [Overview](#overview)
- [Design](#design)
  - [Principles](#principles)
  - [Architecture](#architecture)
  - [Core Abstractions](#core-abstractions)
  - [Evaluation Tracks](#evaluation-tracks)
  - [Provenance and Comparability](#provenance-and-comparability)
- [Directory Structure](#directory-structure)
- [Setup](#setup)
- [Usage Guide](#usage-guide)
  - [Running an Evaluation](#running-an-evaluation)
  - [Writing a Config File](#writing-a-config-file)
  - [Using External Benchmarks](#using-external-benchmarks)
  - [Generating Reports](#generating-reports)
- [Adapters Reference](#adapters-reference)
- [Wiring in Lighthouse Retrieval](#wiring-in-lighthouse-retrieval)
- [Pre-indexing Datasets](#pre-indexing-datasets)
- [Current Limitations](#current-limitations)
- [Future Work](#future-work)

---

## Overview

The framework compares **baseline** performance (model receives only the task prompt) against **augmented** performance (model receives the task prompt plus context retrieved by Lighthouse). For a given configuration of models, context providers, and datasets, it:

1. Loads tasks from an external benchmark via a **DatasetAdapter**.
2. Prepares benchmark workspaces for test-execution tasks before any LLM call.
3. For each runnable `(model, context_provider, task, run)` combination:
   - Retrieves context using a **ContextProvider** (none, oracle, or Lighthouse).
   - Generates a code solution using a **CodeGenerator** (currently AWS Bedrock).
   - Applies the generated output to a temporary workspace as a **CandidateEdit**.
   - Scores the result with a typed **Evaluator** matching the task's evaluation track.
4. Aggregates results into per-track reports with mean, stddev, 95% CI, and delta-over-baseline.

All tasks are **Python-only**. The `Task.language` field is `Literal["python"]` and Pydantic will reject anything else.

---

## Design

### Principles

1. **Provenance is first-class.** Every task and result carries `source_dataset`, `source_instance_id`, `transform_version`, and `comparability_class`. Results from different benchmarks are never silently mixed.

2. **Metrics are typed, not flattened.** Test-execution, match-based, and retrieval-diagnostic tracks each have their own native metric types and summary models. A normalized convenience score is optional and always accompanied by native metrics.

3. **CandidateEdit is the central abstraction.** The LLM produces one of four edit types (file rewrite, multi-file rewrite, unified patch, code completion), which is materialized into a workspace and then scored by the appropriate evaluator.

4. **Adapters are not thin add-ons.** Each adapter maps cleanly into the canonical `Task` model with full provenance and provides the correct `Evaluator` and optional oracle `ContextProvider`.

5. **Lighthouse requires indexed repositories.** `LighthouseProvider` targets `POST /search` and expects `task.metadata.github_repo_id` to be set (injected from `index_registry.json`).

### Architecture

```
CLI (run_eval.py)
    |
    v
EvalRunner
    |---> DatasetAdapter.load()     --> Dataset[Task]
    |---> prepare_dataset_for_run() --> cached base workspaces
    |---> ContextProvider.get_context()
    |---> CodeGenerator.generate()  --> CandidateEdit
    |---> CandidateEdit.apply(workspace)
    |---> Evaluator.evaluate()      --> NativeMetrics
    |---> EvalReport (per-track summaries)
```

The runner prepares test-execution tasks once, then iterates over generation tasks on
`models x context_providers x tasks x num_runs` and retrieval-diagnostic tasks on
`context_providers x tasks x num_runs` with bounded async concurrency.

### Core Abstractions

**Task** (`datasets/schema.py`) -- the canonical unit of work:
- `id`, `provenance` (source, instance, version, comparability class)
- `evaluator_kind`: `test_execution | match | retrieval_diagnostic`
- `output_format`: `file | multi_file | patch | completion`
- `description`: the prompt shown to the LLM
- `test_spec` / `match_spec` / `retrieval_spec`: evaluator-specific configuration
- `oracle_context`: ground-truth context snippets for ablation

**CandidateEdit** (`candidates/base.py`) -- discriminated union:

| Variant | `kind` | `apply()` behavior |
|---|---|---|
| `FileRewrite` | `file` | Writes `content` to `workspace/filename` |
| `MultiFileRewrite` | `multi_file` | Writes each `{path: content}` pair |
| `UnifiedPatch` | `patch` | Runs `git apply` or `patch -p1` |
| `Completion` | `completion` | Appends `text` to an optional target file |

**ContextProvider** (`context/base.py`) -- protocol:

| Implementation | Description |
|---|---|
| `NoneProvider` | Returns `[]`. Establishes baseline. |
| `StaticProvider` | Returns `task.oracle_context`. For ablation/oracle comparison. |
| `LighthouseProvider` | POSTs to `{url}/search`. Real retrieval. |

**Evaluator** (`execution/evaluators/base.py`) -- protocol returning typed `NativeMetrics`:

| Implementation | Track | Metrics |
|---|---|---|
| `PytestEvaluator` | `test_execution` | pass/fail/error counts, pass rate |
| `ExactMatchEvaluator` | `match` | exact match bool, edit similarity |
| `EditSimilarityEvaluator` | `match` | edit similarity (Levenshtein) |
| `BLEUEvaluator` | `match` | BLEU-4 score |
| `RetrievalDiagnosticEvaluator` | `retrieval_diagnostic` | P@k, R@k, MRR |

**CodeGenerator** (`codegen/base.py`) -- protocol:

| Implementation | Models |
|---|---|
| `BedrockGenerator` | `bedrock/<model-id>` — any model available on AWS Bedrock |

### Evaluation Tracks

Results are never mixed across tracks. Each has its own summary model and aggregation logic.

**Test Execution** -- runs a test suite against the LLM's generated code. Metrics: pass rate, resolve rate (fraction of tasks fully passing), stddev, 95% CI. Used by: SWE-bench, BugsInPy, PyBugHive.

**Match** -- compares generated text against ground truth. Metrics: exact match rate, edit similarity, BLEU-4. Used by: CrossCodeEval, RepoBench, RepoQA.

**Retrieval Diagnostic** -- scores the context provider itself, not the generated code. Metrics: Precision@k, Recall@k, MRR. Used by: tasks with `retrieval_spec` and gold snippets.

### Provenance and Comparability

Every `Task` carries a `TaskProvenance`:

```python
class TaskProvenance(BaseModel):
    source_dataset: str          # e.g. "swebench_lite", "crosscodeeval"
    source_instance_id: str      # original ID in the source dataset
    transform_version: str       # adapter version; bump when adapter logic changes
    comparability_class: str     # groups tasks whose scores can be compared
```

Every `EvalResult` copies the task's provenance. Reports group by `comparability_class` so scores from unrelated datasets are never averaged.

---

## Directory Structure

```
evaluation/
  pyproject.toml                          # Package config, deps, build system

  src/lighthouse_eval/
    cli/
      run_eval.py                         # Main CLI implementation
      index_dataset.py                    # Dataset indexing CLI implementation
    config.py                             # EvalConfig, DatasetConfig
    runner.py                             # EvalRunner orchestration loop

    datasets/
      schema.py                           # Task, Dataset, EvalResult, NativeMetrics
      loader.py                           # YAML-based local dataset loader
      adapters/
        __init__.py                       # Adapter registry
        base.py                           # DatasetAdapter protocol + RepoInfo
        swebench.py                       # SWE-bench Lite / Verified
        bugsinpy.py                       # BugsInPy (493 bugs, 17 projects)
        pybughive.py                      # PyBugHive (149 bugs, 11 projects)
        crosscodeeval.py                  # CrossCodeEval (Python split)
        repobench.py                      # RepoBench (Python, cross_file_first)
        repoqa.py                         # RepoQA (Python repos, BLEU-based)
        custom.py                         # Local YAML datasets

    context/
      base.py                             # ContextProvider protocol, ContextSnippet
      none.py                             # NoneProvider (baseline)
      lighthouse.py                       # LighthouseProvider (POST /search)
      static.py                           # StaticProvider (oracle context)

    codegen/
      base.py                             # CodeGenerator protocol
      bedrock.py                          # BedrockGenerator (Converse API)
      prompt.py                           # Prompt construction + response parsing

    candidates/
      base.py                             # CandidateEdit discriminated union

    execution/
      preparation.py                      # Benchmark preflight + cached workspace prep
      workspace.py                        # Workspace creation, cleanup, evaluator dispatch
      evaluators/
        base.py                           # Evaluator protocol
        test_execution.py                 # PytestEvaluator
        match.py                          # ExactMatch, EditSimilarity, BLEU evaluators
        retrieval.py                      # RetrievalDiagnosticEvaluator

    reporting/
      tracks.py                           # TestExecutionSummary, MatchSummary, RetrievalSummary
      results.py                          # EvalReport, aggregation, markdown/JSON output

  scripts/
    run_eval.py                           # Compatibility wrapper for CLI entry point
    index_dataset.py                      # Compatibility wrapper for indexing CLI

  configs/                                # YAML config files (one per dataset)
    swebench.yaml
    bugsinpy.yaml
    pybughive.yaml
    crosscodeeval.yaml
    repobench.yaml
    repoqa.yaml
    smoke/                                # Small baseline smoke-run configs

  Dockerfile                              # Optional eval container image
```

The evaluation package source lives under `evaluation/`; this guide lives at
`docs/evaluation.md`.

---

## Setup

The evaluation framework is a `uv` workspace member within the Lighthouse monorepo.

```bash
# From the monorepo root
uv sync --all-packages
```

This installs `lighthouse-eval` with all dependencies:
- `pydantic` / `pydantic-settings` for data models
- `httpx` for async HTTP (Lighthouse search service)
- `boto3` for AWS Bedrock
- `datasets` for loading HuggingFace benchmarks
- `pyyaml` for config loading
- `pytest` / `pytest-json-report` / `pytest-asyncio` for test execution

### Preferred Runtime

For benchmark smoke runs, the preferred path is the opt-in `eval` container in
`docker-compose.yml`. It keeps the evaluation Python environment reproducible,
mounts benchmark roots and the workspace cache, and talks to the host Docker
daemon through `/var/run/docker.sock` for SWE-bench-style execution.

### Environment Variables

The primary entrypoint for LLM access is **AWS Bedrock**, using the `bedrock/<model-id>` naming convention in configs. Credentials are resolved via the standard boto3 chain — no explicit variables are required if the execution environment is already authenticated (e.g. instance profile, SSO, or a configured AWS profile).

| Variable | Required For | Description |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | Bedrock (`bedrock/*`) | AWS access key (if not using instance profile / SSO) |
| `AWS_SECRET_ACCESS_KEY` | Bedrock (`bedrock/*`) | AWS secret key (if not using instance profile / SSO) |
| `AWS_DEFAULT_REGION` | Bedrock (`bedrock/*`) | AWS region (e.g. `us-east-1`) |

These are only needed when running actual evaluations (not for dry-runs or dataset loading).

---

## Usage Guide

### Running an Evaluation

```bash
cd evaluation/

# Dry run — loads dataset and prints first task, no LLM calls
uv run python scripts/run_eval.py -v run --config configs/swebench.yaml --dry-run

# Full run
uv run python scripts/run_eval.py run --config configs/swebench.yaml
```

For the first baseline smoke pass across all targeted datasets, use the
`configs/smoke/` configs. They are `none`-provider only, `num_runs: 1`, and
cap each dataset to 3 instances.

```bash
# From the repo root, inside the opt-in eval container
docker compose --profile eval run --rm \
  eval python evaluation/scripts/run_eval.py \
  run --config evaluation/configs/smoke/swebench.yaml
```

Artifacts are written back to the host under `evaluation/results/...`, and
prepared benchmark workspaces are cached under `evaluation/.cache/workspaces/`.

The CLI has two subcommands:

| Command | Description |
|---|---|
| `run --config <path> [--dry-run]` | Load config, load dataset, run evaluations, save results + reports |
| `report --results <path>` | Re-generate reports from an existing JSONL results file |

### Writing a Config File

Configs are YAML files with this structure:

```yaml
models:
  - "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"

context_providers:
  - "none"              # baseline: no context
  - "static:oracle"     # oracle: ground-truth context from dataset
  - "lighthouse"        # real retrieval (requires indexed repos)

dataset:
  adapter: "swebench"
  source: "princeton-nlp/SWE-bench_Lite"
  split: "test"
  max_instances: 50     # optional: cap tasks for faster iteration

num_runs: 3             # repetitions per combination for variance estimation
search_service_url: "http://localhost:8002"
output_dir: "results/swebench/"
workspace_cache_dir: "../.cache/workspaces"
concurrency: 4

metadata:
  index_registry: "datasets/swebench/index_registry.json"
```

### Using External Benchmarks

All supported benchmarks load from HuggingFace (or local clones) via adapters. See `configs/` for ready-made configs for each. Quick examples:

```yaml
# SWE-bench Lite (repo-level repair, Docker recommended)
dataset:
  adapter: "swebench"
  source: "princeton-nlp/SWE-bench_Lite"
  split: "test"

# CrossCodeEval (cross-file completion with oracle context)
dataset:
  adapter: "crosscodeeval"
  source: "amazon-science/cceval"
  split: "test"

# BugsInPy (requires a local clone)
dataset:
  adapter: "bugsinpy"
  path: "/path/to/bugsinpy-clone"
```

The first time you use a HuggingFace adapter, the dataset will be downloaded and cached automatically.

For test-execution tracks, the runner now prepares a cached base workspace for
each task before evaluation starts. That prep phase is fail-fast: missing
benchmark roots, missing checkout tooling, or missing SWE-bench Docker images
abort the run before any LLM call is made.

### Generating Reports

Reports are generated automatically after a run. To regenerate from saved results:

```bash
uv run python scripts/run_eval.py report --results results/swebench/results_1234567890.jsonl
```

This produces:
- `report.json` -- machine-readable per-track summaries
- `report.md` -- human-readable markdown tables

Reports include separate sections for each evaluation track (test execution, match, retrieval diagnostics), with mean, stddev, 95% CI, and comparability class annotations.

---

## Adapters Reference

| Adapter | Source | Track | Output Format | Oracle Context |
|---|---|---|---|---|
| `swebench` | HuggingFace | test_execution | patch | No |
| `bugsinpy` | Local clone | test_execution | patch | No |
| `pybughive` | Local clone | test_execution | patch | No |
| `crosscodeeval` | HuggingFace / JSONL | match | completion | Yes |
| `repobench` | HuggingFace | match | completion | Yes |
| `repoqa` | HuggingFace | match (BLEU) | completion | Yes |
| `custom` | Local YAML | any | any | Optional |

Adapters with oracle context enable three-way comparison: no context vs. oracle vs. Lighthouse retrieval. The delta between oracle and Lighthouse directly measures retrieval quality.

---

## Wiring in Lighthouse Retrieval

The Lighthouse search service runs at `http://localhost:8002` by default (see `docker-compose.yml`). To include it in an evaluation, add `"lighthouse"` to `context_providers` and optionally configure `search_service_url`.

```yaml
context_providers:
  - "none"
  - "lighthouse"

search_service_url: "http://localhost:8002"
```

When running inside the `eval` container on the Compose network, use
`http://search:8002` instead of `http://localhost:8002`.

### Configuring Search Methods

The eval config supports the `lighthouse:<method>` naming pattern for selecting
named retrieval methods. Today the implemented path is the default hybrid
search; as additional search methods are added to the search service and eval
client, they can be exposed through the same provider syntax.

```yaml
context_providers:
  - "none"                 # baseline
  - "lighthouse"           # current default
  - "lighthouse:hybrid"    # explicit equivalent of the default
```

Each configured variant becomes a separate column in reports. Future search
methods should reuse this naming convention once support is added end to end.

`LighthouseProvider` sends `POST /search` with:

```json
[
  {
    "method": "hybrid",
    "query": "<task description>",
    "top_k": 10,
    "github_repo_id": "<from task.metadata, if present>",
    "branch": "<from task.metadata, if present>"
  }
]
```

If the service is unavailable, it logs a warning and returns empty context (so runs don't crash).

---

## Pre-indexing Datasets

`lighthouse` context is only meaningful for tasks tied to repositories that are already indexed by the ingestion service.

Before running evals with `lighthouse`, run:

```bash
# Dry run: resolves repos via GitHub API and prints what would be indexed (no ingestion calls)
uv run python scripts/index_dataset.py \
  --config configs/swebench.yaml \
  --github-token "$GITHUB_TOKEN" \
  --dry-run

# Full run: index and wait for completion
uv run python scripts/index_dataset.py \
  --config configs/swebench.yaml \
  --ingestion-url http://localhost:8001 \
  --github-token "$GITHUB_TOKEN" \
  --output datasets/swebench/index_registry.json
```

What this does:
- Loads the dataset adapter from your config
- Calls `adapter.get_repos(...)` to discover referenced repos
- Calls `POST /index` on ingestion service
- Polls `GET /status/{github_repo_id}` until all requested branches are `indexed`
- Writes `index_registry.json` mapping `owner/repo -> github_repo_id + branch`

`run_eval.py` auto-loads `index_registry.json` from:
- `metadata.index_registry` in config (if set), else
- `<dataset.path>/index_registry.json` (for local datasets)

It then injects `github_repo_id` and `branch` into each task's `metadata` before evaluation.

---

## Current Limitations

**Not yet validated at full benchmark scale with live LLM calls.** The framework now prepares cached benchmark workspaces and supports real smoke runs, but large benchmark sweeps with live LLM traffic will still be the first place that rate limits, timeout tuning, and prompt-format edge cases show up.

**Heavyweight benchmark assets are still bring-your-own.** SWE-bench still requires existing Docker images, and BugsInPy/PyBugHive still require local benchmark roots plus any benchmark-specific checkout tooling. The runner validates these prerequisites early, but it does not install tooling or build/pull images automatically.

**Eval container is preferred, not mandatory.** Host-run evaluation still works, but the documented smoke path is the opt-in Compose `eval` service because it provides a more reproducible environment for benchmark prep and execution.

**Generation is Bedrock-only today.** The evaluation runner currently accepts
`bedrock/<model-id>` models only. If we add more generator backends later, they
should be documented explicitly.

**Custom/local datasets are not Lighthouse-indexable yet.** The ingestion API indexes GitHub repositories (`github_repo_id`, `repo_url`, `full_name`). Local-only workspaces in `custom` datasets currently support `none` and `static:oracle`, but not `lighthouse`, until local indexing support is added.

**No caching of LLM responses.** Each run re-queries the LLM API. For expensive models or large datasets, this can be costly. Response caching would significantly reduce iteration costs.

**Single-process execution.** The runner uses `asyncio` concurrency within a single process. For very large benchmark runs (1000+ tasks x multiple models), distributed execution across machines is not supported.

---

## Future Work

**Custom datasets:**
- Curated multi-file, multi-repo, and library-integration tasks with real GitHub repos
- Mutation-based dataset generation (AST-level operators: cross-file ref, API contract, invariant break)
- Task scaffolding script for quickly adding new curated tasks

**Execution environment improvements:**
- Better benchmark-specific setup/install discovery for BugsInPy and PyBugHive
- More aggressive workspace reuse across tasks from the same repository
- Optional automation for building or pulling missing SWE-bench images

**LLM response caching:**
- Cache `(model, prompt_hash) -> raw_response` to avoid redundant API calls across runs
- Invalidate on prompt template changes

**Distributed execution:**
- Split `models x providers x tasks` matrix across workers
- Centralized result collection and reporting

**Additional reporting:**
- Per-task breakdown (which specific tasks improve most with context?)
- Statistical significance tests (paired t-test, bootstrap CI)
- Visualization dashboards (pass rate curves, retrieval quality heatmaps)

**Indexing workflow improvements:**
- Add incremental refresh support to `index_dataset.py` (skip already-indexed repos/branches)
- Validate that every task with `lighthouse` has a matching registry entry before run start
- Support per-dataset branch mapping when benchmarks pin non-default branches

**Retrieval method support:**
- Add additional named search methods beyond the current hybrid path
- Keep the eval-side provider syntax and request shaping aligned with search-service capabilities

**More adapters:**
- SWE-bench++ (multi-language, filter to Python)
- Aider benchmark (edit-format evaluation)

**Integration tests:**
- End-to-end test with a mock LLM server returning canned responses
- Adapter integration tests that load a small slice of each benchmark
- Regression tests for prompt template changes
