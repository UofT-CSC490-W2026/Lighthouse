# Eval Package

This document describes the practical evaluation workflow in this repository.
It keeps the package-oriented style while adding a runbook section for
reproducible synthetic and SWE-bench experiments.

---

## Scope

### Supported evaluation tracks

- **Synthetic** (fast, controlled families): full matrix runner exists.
- **SWE-bench** (official harness-backed): run commands exist, but no single built-in matrix command yet.

### Key CLI commands

- Synthetic:
  - `run-synthetic-experiment`
  - `pass-at-k-synthetic`
  - `run-synthetic-matrix`
- SWE-bench:
  - `show-slice`
  - `prepare-images`
  - `index-repos`
  - `prepare-wiki`
  - `generate-baseline`
  - `generate-lighthouse`
  - `evaluate`
  - `summarize`

---

## Synthetic Benchmark Motivation and Defensibility

Synthetic families currently under `packages/eval/src/eval/synthetic/families/`:

- `synthetic-ab-contracts` (`api_contract_mismatch`)
- `synthetic-wrong-operator` (`logic_wrong_operator`)
- `synthetic-type-coercion` (`data_type_coercion`)
- `synthetic-doc-behavior` (`doc_behavior_mismatch`)
- `synthetic-api-feature` (`feature_api_integration`)
- `synthetic-doc-feature` (`feature_doc_guided`)

### Why these are defensible

- **Controlled causal structure**: each task has known buggy and gold patches.
- **Executable ground truth**: every task is validated by local pytest behavior:
  - buggy state fails
  - gold-patched state passes
- **No answer leakage by default**: prompts avoid embedding gold patch content.
- **Task-type diversity**: includes both repair and feature tasks.
- **Search-method stress**:
  - code-centric families evaluate lexical/localization capability
  - doc/API families evaluate information retrieval utility
- **Deterministic sampling**: `seed` + `task_count` produce reproducible subsets.

### Defensibility checklist

For each reported synthetic result set, record:

- family names + versions
- task_count, seed, task_type (if filtered)
- codegen model, region
- embedding strategy/model(s)
- retrieval context source and top-k
- run ids + artifact paths
- pass@k definition and k set

---

## Requirements

- Python + deps:
  - `uv sync --all-packages --dev`
- Infra/services:
  - `docker compose up -d postgres ingestion ingestion-worker search`
- If migrations are needed:
  - `cd packages/db && uv run alembic upgrade head && cd ../..`
- Optional health checks:
  - `curl -sf http://localhost:8001/health`
  - `curl -sf http://localhost:8002/health`

---

## Runbook

`run-synthetic-matrix` is the matrix runner. It consumes a JSON config.

### 4.1 Example matrix config

Create `configs/synthetic-matrix-openai-embed.json`:

```json
{
  "families": ["all"],
  "context_sources": ["code", "wiki", "combined", "ast"],
  "chunking_strategies": ["base", "ast"],
  "codegen_models": [
    "openai/gpt-5.4",
    "bedrock/us.amazon.nova-pro-v1:0"
  ],
  "embedding_models": [
    "text-embedding-3-large"
  ],
  "embedding_strategy": "openai",
  "repeat_count": 3,
  "k_values": [1, 2, 3],
  "task_count": 10,
  "top_k": 5
}
```

Notes:

- `families: ["all"]` expands all checked-in synthetic families.
- `context_source="ast"` requires `chunking_strategy="ast"` (enforced).
- `embedding_strategy` is single-valued per run. To sweep OpenAI + Bedrock embeddings, run two matrix configs.

### 4.2 Dry-run first (recommended)

```bash
uv run eval run-synthetic-matrix \
  --config configs/synthetic-matrix-openai-embed.json \
  --run-prefix synth-openai-dry \
  --dry-run \
  --output-root .cache/eval/synthetic_experiments/synth/openai
```

### 4.3 Execute matrix

```bash
uv run eval run-synthetic-matrix \
  --config configs/synthetic-matrix-openai-embed.json \
  --run-prefix synth-openai \
  --ingestion-url http://localhost:8001 \
  --search-url http://localhost:8002 \
  --output-root .cache/eval/synthetic_experiments/synth/openai \
  --max-parallel-cells 4 \
  --continue-on-error
```

Parallel execution notes:

- `--max-parallel-cells > 1` enables matrix-cell parallelism.
- The runner preprocesses each `(family, chunking_strategy, embedding_model)` group once
  (workspace prep, indexing, wiki), then executes cells in parallel with preprocessing
  skipped.

### 4.4 Artifacts to report

Per matrix output root:

- `matrix_rows.json` (cell-level score + pass@k + efficiency fields)
- `matrix_rows.md` (combined score/pass@k and efficiency sections)
- `matrix_efficiency.json`
- `matrix_efficiency.txt`
- `heatmaps/*.png` (score and pass@k, one file per embedding config)
- `pass_at_k/*.pass_at_k.txt`

Heatmap layout:

- x-axis: codegen model
- y-axis: `context_source`
- separate panel/file per embedding model (and per family + chunking strategy group)

### 4.5 Efficiency metrics currently exposed

For each matrix cell:

- mean total duration (seconds)
- mean generation tokens
- mean generation cost (USD, estimated from checked-in pricing catalogs)
- per-repeat values for the above

These are now visible in:

- `matrix_rows.*`
- `matrix_efficiency.*`

---

### Synthetic Pass@k

Pass@k is first-class for synthetic and is integrated into matrix output.  
Manual aggregation remains available:

```bash
uv run eval pass-at-k-synthetic \
  --run-id run-a --run-id run-b --run-id run-c \
  --k 1 --k 2 --k 3
```

Formula used:

- `pass@k = 1 - C(n-c, k) / C(n, k)`
  - `n`: total sampled runs
  - `c`: successful runs for that task

---

### SWE-bench with Configuration Parity

There is no built-in `run-swebench-matrix` command yet.  
Use a config-driven sweep script and keep parity by reusing the same model/context/top-k selections as synthetic.

#### Current parity constraints

- SWE-bench CLI does **not** currently expose embedding override flags per run.
- SWE-bench generation commands are currently **Bedrock-only**.
- Synthetic matrix supports OpenAI + Bedrock codegen, plus runtime embedding strategy/model overrides.

To keep parity today:

- use the **intersection** of supported codegen models (Bedrock models) and retrieval contexts (`code`/`wiki`) across both tracks
- pin SWE-bench embedding backend by service env/config before each sweep batch
- run separate sweeps for each embedding backend/model setting (same approach as synthetic multi-config)

### 6.2 SWE-bench runbook (single config batch)

1) Show/select slice:

```bash
uv run eval show-slice --dataset-name princeton-nlp/SWE-bench_Lite --split test --max-instances 50
```

2) Prepare images:

```bash
uv run eval prepare-images \
  --dataset-name princeton-nlp/SWE-bench_Lite \
  --split test \
  --max-instances 50 \
  --max-workers 1
```

3) Index repos + wiki preprocess:

```bash
uv run eval index-repos \
  --dataset-name princeton-nlp/SWE-bench_Lite \
  --split test \
  --max-instances 50 \
  --ingestion-url http://localhost:8001 \
  --output .cache/eval/swebench/repo-registry.json
```

4) Generate + evaluate baseline:

```bash
uv run eval generate-baseline \
  --dataset-name princeton-nlp/SWE-bench_Lite \
  --split test \
  --max-instances 50 \
  --model bedrock/us.amazon.nova-pro-v1:0 \
  --output .cache/eval/swebench/baseline.jsonl \
  --overwrite

uv run eval evaluate \
  --dataset-name princeton-nlp/SWE-bench_Lite \
  --split test \
  --max-instances 50 \
  --predictions .cache/eval/swebench/baseline.jsonl \
  --run-id swebench-baseline-nova-pro \
  --max-workers 1
```

5) Generate + evaluate retrieval runs (repeat for `code` and `wiki`):

```bash
uv run eval generate-lighthouse \
  --dataset-name princeton-nlp/SWE-bench_Lite \
  --split test \
  --max-instances 50 \
  --model bedrock/us.amazon.nova-pro-v1:0 \
  --repo-registry .cache/eval/swebench/repo-registry.json \
  --search-url http://localhost:8002 \
  --context-source code \
  --top-k 5 \
  --output .cache/eval/swebench/code.jsonl \
  --overwrite

uv run eval evaluate \
  --dataset-name princeton-nlp/SWE-bench_Lite \
  --split test \
  --max-instances 50 \
  --predictions .cache/eval/swebench/code.jsonl \
  --run-id swebench-code-nova-pro \
  --max-workers 1
```

6) Summarize:

```bash
uv run eval summarize \
  --predictions .cache/eval/swebench/code.jsonl \
  --run-id swebench-code-nova-pro
```

### 6.3 Config-driven SWE-bench sweep script (recommended)

Use your synthetic matrix config as the source of truth and iterate models/contexts in shell/Python.  
Example shell shape:

```bash
#!/usr/bin/env bash
set -euo pipefail

DATASET="princeton-nlp/SWE-bench_Lite"
SPLIT="test"
N=50
REGISTRY=".cache/eval/swebench/repo-registry.json"
OUTROOT=".cache/eval/swebench"

for MODEL in "bedrock/us.amazon.nova-pro-v1:0" "bedrock/us.amazon.nova-lite-v1:0"; do
  # baseline
  uv run eval generate-baseline \
    --dataset-name "$DATASET" --split "$SPLIT" --max-instances "$N" \
    --model "$MODEL" \
    --output "$OUTROOT/${MODEL//\//__}.baseline.jsonl" \
    --overwrite

  uv run eval evaluate \
    --dataset-name "$DATASET" --split "$SPLIT" --max-instances "$N" \
    --predictions "$OUTROOT/${MODEL//\//__}.baseline.jsonl" \
    --run-id "swebench-${MODEL//\//-}-baseline" \
    --max-workers 1

  for CTX in code wiki; do
    uv run eval generate-lighthouse \
      --dataset-name "$DATASET" --split "$SPLIT" --max-instances "$N" \
      --model "$MODEL" \
      --repo-registry "$REGISTRY" \
      --search-url http://localhost:8002 \
      --context-source "$CTX" \
      --top-k 5 \
      --output "$OUTROOT/${MODEL//\//__}.${CTX}.jsonl" \
      --overwrite

    uv run eval evaluate \
      --dataset-name "$DATASET" --split "$SPLIT" --max-instances "$N" \
      --predictions "$OUTROOT/${MODEL//\//__}.${CTX}.jsonl" \
      --run-id "swebench-${MODEL//\//-}-${CTX}" \
      --max-workers 1
  done
done
```

---

## Reporting Template for Tables/Figures

For each synthetic matrix figure/table, include:

- benchmark track: synthetic
- families included
- model sweep lists
- embedding sweep lists + strategy
- retrieval contexts + chunking strategies
- heatmap orientation (`x=codegen`, `y=context_source`) and panel split (`per-embedding`)
- repeats and k-values
- score metric and pass@k metric definitions
- cost source (checked-in pricing catalogs)

For SWE-bench tables:

- dataset and split
- instance selection (`max-instances` or explicit IDs)
- same model/context/top-k settings as synthetic where applicable
- note any unsupported parity dimension (currently per-run embedding override in CLI)

---

## Troubleshooting

- **Indexing/wiki 500s**: restart services + run DB migrations.
- **No heatmaps**: ensure `matplotlib` installed; `seaborn` is optional.
- **OpenAI model fails**: verify `OPENAI_API_KEY`.
- **Bedrock model invalid**: use inference-profile style IDs (`bedrock/us.amazon...`).
- **Large matrix instability**: use `--continue-on-error` and inspect `matrix_rows.json` `error` fields.

---

## Reproducibility Recommendations

- Keep all config files under `configs/` and version-control them.
- Use deterministic seeds for synthetic runs.
- Encode run identity in `--run-prefix` (`<track>-<modelset>-<date>`).
- Never overwrite archival outputs; write to dated roots.
- Store final artifact root paths directly in your manuscript appendix.
