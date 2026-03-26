# Lighthouse Evaluation Framework

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
2. For each `(model, context_provider, task, run)` combination:
   - Retrieves context using a **ContextProvider** (none, oracle, or Lighthouse).
   - Generates a code solution using a **CodeGenerator** (Bedrock, OpenAI, Anthropic).
   - Applies the generated output to a temporary workspace as a **CandidateEdit**.
   - Scores the result with a typed **Evaluator** matching the task's evaluation track.
3. Aggregates results into per-track reports with mean, stddev, 95% CI, and delta-over-baseline.

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
    |---> ContextProvider.get_context()
    |---> CodeGenerator.generate()  --> CandidateEdit
    |---> CandidateEdit.apply(workspace)
    |---> Evaluator.evaluate()      --> NativeMetrics
    |---> EvalReport (per-track summaries)
```

The runner iterates over `models x context_providers x tasks x num_runs` with bounded async concurrency.

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
  README.md                               # This file

  src/lighthouse_eval/
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
    run_eval.py                           # CLI entry point
    index_dataset.py                      # Pre-index repos and write index_registry.json

  configs/                                # YAML config files (one per dataset)
    swebench.yaml
    bugsinpy.yaml
    pybughive.yaml
    crosscodeeval.yaml
    repobench.yaml
    repoqa.yaml
```

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

### Configuring Search Methods

The search service supports multiple named retrieval methods that can be compared independently or combined. Specify them with the `lighthouse:<method>` syntax:

```yaml
context_providers:
  - "none"                 # baseline
  - "lighthouse"           # default (all methods combined)
  - "lighthouse:doc"       # only doc-based retrieval
  - "lighthouse:ast"       # only AST-based retrieval
  - "lighthouse:doc,ast"   # both, fused via RRF
```

Each variant becomes a separate column in reports. New methods are registered server-side in `services/search/src/search/main.py` and are immediately available without any client changes.

`LighthouseProvider` sends `POST /search` with:

```json
{
  "query": "<task description>",
  "top_k": 10,
  "search_methods": ["doc"],
  "github_repo_id": "<from task.metadata, if present>",
  "branch": "<from task.metadata, if present>"
}
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

**Not yet validated end-to-end with live LLM calls.** The framework has been smoke-tested with dry-runs, dataset loading, adapter instantiation, and unit-level evaluator logic. Full end-to-end runs with real LLM API calls have not yet been performed. The first real run will likely surface issues in response parsing, workspace materialization edge cases, or timeout tuning.

**SWE-bench and BugsInPy adapters assume local infrastructure.** SWE-bench needs Docker with per-instance images (~120GB disk). BugsInPy and PyBugHive need local clones of their respective repositories with `bugsinpy-checkout` or equivalent tooling installed. The adapters load task metadata but do not automate environment provisioning.

**Test execution in sandboxed workspaces.** `PytestEvaluator` runs `pytest` as a subprocess in a temp directory. It does not install dependencies, set up virtualenvs, or run Docker containers. For benchmarks that need specific environments (SWE-bench, BugsInPy, PyBugHive), additional workspace setup logic is needed.

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
- Docker-based workspace execution for SWE-bench, BugsInPy, PyBugHive
- Automatic dependency installation in sandboxed workspaces
- Per-adapter workspace setup hooks (e.g. `bugsinpy-checkout`)

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

**More adapters:**
- SWE-bench++ (multi-language, filter to Python)
- Aider benchmark (edit-format evaluation)

**Integration tests:**
- End-to-end test with a mock LLM server returning canned responses
- Adapter integration tests that load a small slice of each benchmark
- Regression tests for prompt template changes
