# Eval Package

This document describes the new evaluation package under `packages/eval/`.

It is intentionally narrower than the older `evaluation/` framework. The goal
is to establish a reliable SWE-bench baseline path first, with manual checks
after each step, before adding more datasets or more retrieval-aware behavior.

For the broader roadmap, see `docs/eval-package-plan.md`. This document only
covers the package as it exists today.

Unless otherwise noted, all paths shown below are relative to the repository
root.

## Scope

Current scope:

- load a SWE-bench slice from Hugging Face
- inspect the selected slice
- prepare SWE-bench Docker images for that slice
- generate baseline SWE-bench prediction JSONL with Bedrock
- evaluate predictions with the official SWE-bench harness
- summarize harness results in a small human-readable report

Current non-scope:

- Lighthouse retrieval integration
- result comparison
- support for datasets other than SWE-bench

## Design

The package is host-first and harness-first.

Host-first means the commands are meant to be run directly on the developer
machine with `uv`, not through a separate orchestration container.

Harness-first means we rely on the official SWE-bench harness for benchmark
runtime concerns such as Docker image preparation, rather than re-implementing
that behavior ourselves.

Today the package contains:

```text
packages/eval/
  pyproject.toml
  src/eval/
    __init__.py
    cli.py
    slice.py
    harness.py
    bedrock.py
    prompts.py
    predictions.py
    summary.py
```

### `slice.py`

`slice.py` is the dataset-selection layer.

It loads a SWE-bench dataset split and converts rows into a small
`SWEBenchTask` dataclass containing:

- `instance_id`
- `repo`
- `base_commit`
- `version`
- `problem_statement`

It supports two selection modes:

- `--max-instances N`
- repeated `--instance-id ...`

### `harness.py`

`harness.py` is the wrapper around the official
`swebench.harness.prepare_images` entrypoint.

It currently does four things:

1. resolves the current Docker endpoint
2. calls the official harness for a chosen SWE-bench slice
3. streams harness log files while the build runs
4. verifies that the expected instance image tags exist afterward

The default harness work directory is:

```text
.cache/eval/swebench_harness
```

Harness build logs are written under:

```text
.cache/eval/swebench_harness/logs/build_images
```

### `bedrock.py`, `prompts.py`, and `predictions.py`

These files make up the current baseline generation path.

`bedrock.py` contains a small Bedrock wrapper that:

- accepts models in `bedrock/<model-id>` format
- defaults baseline generation to `us-east-1`
- calls the Bedrock `converse` API
- returns the text content from the model response

`prompts.py` contains the minimal baseline prompt used for SWE-bench today.
It uses only benchmark metadata from the selected task:

- `instance_id`
- `repo`
- `base_commit`
- `version`
- `problem_statement`

`predictions.py` turns model responses into harness-compatible JSONL rows and
writes them incrementally to disk.

### `summary.py`

`summary.py` reads the harness outputs back from disk.

It locates:

- the aggregate run report written at the harness workdir root
- the per-instance `report.json` files under `logs/run_evaluation/...`

It then turns those files into a smaller summary view containing:

- aggregate counts such as resolved and unresolved instances
- per-instance status
- whether the generated patch applied
- how many `FAIL_TO_PASS` tests passed or failed
- any remaining failing `FAIL_TO_PASS` test names

### Image Naming

The expected instance image names currently follow the official SWE-bench
harness convention:

```text
sweb.eval.x86_64.<instance_id>:latest
```

For example:

```text
sweb.eval.x86_64.astropy__astropy-12907:latest
```

This is still true on Apple Silicon / ARM machines. The harness defaults to the
`x86_64` image naming convention, and Docker Desktop handles the underlying
emulation/runtime behavior.

## Requirements

You should have the following available on the host:

- `uv`
- `python3`
- `docker`
- a working Docker daemon / Docker Desktop context
- network access to Hugging Face for SWE-bench dataset loading
- AWS credentials with access to Bedrock if you want to generate predictions

Optional but recommended:

- `HUGGINGFACE_HUB_TOKEN`

If `HUGGINGFACE_HUB_TOKEN` is set, the harness wrapper will also expose it to
the official SWE-bench tooling as `HF_TOKEN`.

## CLI

The current CLI entrypoint is:

```bash
uv run --package eval python -m eval.cli ...
```

Available commands today:

- `show-slice`
- `prepare-images`
- `generate-baseline`
- `evaluate`
- `summarize`

### `show-slice`

Print a selected SWE-bench slice without preparing any Docker images.

Supported arguments:

- `--dataset-name`
- `--split`
- `--max-instances`
- `--instance-id`

### `prepare-images`

Load a selected SWE-bench slice and prepare the required SWE-bench Docker
images for that slice.

Supported arguments:

- `--dataset-name`
- `--split`
- `--max-instances`
- `--instance-id`
- `--workdir`
- `--max-workers`

### `generate-baseline`

Load a selected SWE-bench slice, generate one baseline patch per task with
Bedrock, and write the results to a predictions `.jsonl` file.

Supported arguments:

- `--dataset-name`
- `--split`
- `--max-instances`
- `--instance-id`
- `--model`
- `--output`
- `--region-name`
- `--temperature`
- `--max-tokens`
- `--overwrite`

### `evaluate`

Load a selected SWE-bench slice, run the official harness against an existing
predictions file, and print the resulting report path and run log directory.

Supported arguments:

- `--dataset-name`
- `--split`
- `--max-instances`
- `--instance-id`
- `--predictions`
- `--run-id`
- `--workdir`
- `--max-workers`
- `--timeout-seconds`
- `--cache-level`

### `summarize`

Read an existing SWE-bench harness run and print a compact human-readable
summary.

Supported arguments:

- `--predictions`
- `--run-id`
- `--workdir`

## Run Book

### 1. Show The Slice

From the repo root:

```bash
uv run --package eval python -m eval.cli show-slice --max-instances 3
```

Expected output shape:

```text
SWE-bench slice: 3 instance(s) from princeton-nlp/SWE-bench_Lite [test]
1. astropy__astropy-12907
   repo: astropy/astropy
   base_commit: ...
   version: ...
2. astropy__astropy-14182
   repo: astropy/astropy
   base_commit: ...
   version: ...
3. astropy__astropy-14365
   repo: astropy/astropy
   base_commit: ...
   version: ...
```

This confirms:

- the dataset is reachable
- the slice selection logic is working
- the chosen instance ids are the ones you expect

### 2. Prepare Images For One Instance

The recommended first manual image-prep test is a single instance:

```bash
uv run --package eval python -m eval.cli prepare-images \
  --instance-id astropy__astropy-12907 \
  --max-workers 1
```

Expected output shape at the beginning:

```text
SWE-bench slice: 1 instance(s) from princeton-nlp/SWE-bench_Lite [test]
1. astropy__astropy-12907
   repo: astropy/astropy
   base_commit: ...
   version: ...

Preparing 1 SWE-bench image(s)
Using Docker endpoint: unix://...
Harness workdir: .cache/eval/swebench_harness
Instance ids:
  - astropy__astropy-12907
```

Then, depending on cache state, you should see either:

- fresh build output from the official harness, or
- a fast path where the harness reports that the images already exist

Typical harness progress includes lines such as:

- `Building base image (...)`
- `Total environment images to build: ...`
- `Building instance images for ... instances`
- `Streaming harness log: ...`

Expected success at the end:

```text
Verified image: sweb.eval.x86_64.astropy__astropy-12907:latest
Prepared images:
  - sweb.eval.x86_64.astropy__astropy-12907:latest
```

Host-side verification:

```bash
docker image inspect sweb.eval.x86_64.astropy__astropy-12907:latest >/dev/null && echo "image ready"
```

### 3. Prepare Images For The 3-Instance Smoke Slice

After the single-instance test succeeds, prepare the slice we have been using
for smoke work:

```bash
uv run --package eval python -m eval.cli prepare-images \
  --max-instances 3 \
  --max-workers 1
```

This selects the first three instances from the SWE-bench Lite `test` split,
which currently are:

- `astropy__astropy-12907`
- `astropy__astropy-14182`
- `astropy__astropy-14365`

If the first image was already built during the single-instance test, the
harness should usually skip rebuilding it and only build what is still missing.

Expected success at the end:

```text
Verified image: sweb.eval.x86_64.astropy__astropy-12907:latest
Verified image: sweb.eval.x86_64.astropy__astropy-14182:latest
Verified image: sweb.eval.x86_64.astropy__astropy-14365:latest
Prepared images:
  - sweb.eval.x86_64.astropy__astropy-12907:latest
  - sweb.eval.x86_64.astropy__astropy-14182:latest
  - sweb.eval.x86_64.astropy__astropy-14365:latest
```

Host-side verification:

```bash
docker image inspect \
  sweb.eval.x86_64.astropy__astropy-12907:latest \
  sweb.eval.x86_64.astropy__astropy-14182:latest \
  sweb.eval.x86_64.astropy__astropy-14365:latest >/dev/null && echo "images ready"
```

### 4. Generate Baseline Predictions

Once the slice is selected and the image-prep command is behaving as expected,
generate a baseline predictions file.

For the first manual check, use one instance and write to a throwaway path:

```bash
uv run --package eval python -m eval.cli generate-baseline \
  --instance-id astropy__astropy-12907 \
  --output .cache/eval/runs/baseline-1.jsonl
```

The default model is currently:

```text
bedrock/us.amazon.nova-lite-v1:0
```

The default Bedrock region is currently:

```text
us-east-1
```

If you want a different Bedrock model, override it explicitly:

```bash
uv run --package eval python -m eval.cli generate-baseline \
  --instance-id astropy__astropy-12907 \
  --model bedrock/<your-model-id> \
  --output .cache/eval/runs/baseline-1.jsonl
```

Expected output shape:

```text
SWE-bench slice: 1 instance(s) from princeton-nlp/SWE-bench_Lite [test]
1. astropy__astropy-12907
   repo: astropy/astropy
   base_commit: ...
   version: ...
Model: bedrock/us.amazon.nova-lite-v1:0
Bedrock region: us-east-1
Output file: .cache/eval/runs/baseline-1.jsonl
[1/1] Generating baseline patch for astropy__astropy-12907
    wrote ... patch chars
Wrote 1 prediction(s) to .cache/eval/runs/baseline-1.jsonl
```

Then inspect the file directly:

```bash
sed -n '1,5p' .cache/eval/runs/baseline-1.jsonl
```

Each JSONL row currently includes:

- `instance_id`
- `model_name_or_path`
- `model_patch`
- `full_output`

To inspect just the generated patch:

```bash
python3 - <<'PY'
import json
from pathlib import Path

row = json.loads(Path(".cache/eval/runs/baseline-1.jsonl").read_text().splitlines()[0])
print(row["model_patch"])
PY
```

To verify that the patch begins like a unified diff:

```bash
python3 - <<'PY'
import json
from pathlib import Path

row = json.loads(Path(".cache/eval/runs/baseline-1.jsonl").read_text().splitlines()[0])
patch = row["model_patch"]
print("starts_with_unified_diff =", patch.startswith("--- a/"))
print("instance_id =", row["instance_id"])
PY
```

For the 3-instance smoke slice:

```bash
uv run --package eval python -m eval.cli generate-baseline \
  --max-instances 3 \
  --output .cache/eval/runs/baseline-3.jsonl
```

Then verify the file has three rows:

```bash
wc -l .cache/eval/runs/baseline-3.jsonl
```

### 5. Evaluate Predictions

Once you have a predictions file, run the official SWE-bench harness through
the new wrapper.

For a single-instance manual test:

```bash
uv run --package eval python -m eval.cli evaluate \
  --instance-id astropy__astropy-12907 \
  --predictions .cache/eval/runs/baseline-1.jsonl \
  --run-id baseline-1-smoke \
  --max-workers 1
```

Use a fresh `--run-id` for each new evaluation attempt so the harness does not
reuse prior per-instance reports from the same run id.

Expected output shape at the beginning:

```text
SWE-bench slice: 1 instance(s) from princeton-nlp/SWE-bench_Lite [test]
1. astropy__astropy-12907
   repo: astropy/astropy
   base_commit: ...
   version: ...
Evaluating 1 SWE-bench prediction(s)
Run id: baseline-1-smoke
Using Docker endpoint: unix://...
Harness workdir: .cache/eval/swebench_harness
Predictions file: .cache/eval/runs/baseline-1.jsonl
Instance ids:
  - astropy__astropy-12907
```

During the run you should see newly discovered harness log files and per-log
stream output, for example:

- `Streaming harness log: run_evaluation/...`
- `[harness:run_evaluation/.../run_instance.log] ...`

At the end, the official harness should print a summary similar to:

```text
Total instances: 1
Instances submitted: 1
Instances completed: 1
Instances resolved: ...
Instances unresolved: ...
Report written to bedrock__us.amazon.nova-lite-v1:0.baseline-1-smoke.json
```

and the wrapper should print:

```text
Evaluation report: .cache/eval/swebench_harness/bedrock__us.amazon.nova-lite-v1:0.baseline-1-smoke.json
Run log directory: .cache/eval/swebench_harness/logs/run_evaluation/baseline-1-smoke/bedrock__us.amazon.nova-lite-v1:0
```

Then inspect the report:

```bash
cat .cache/eval/swebench_harness/bedrock__us.amazon.nova-lite-v1:0.baseline-1-smoke.json
```

To inspect the per-instance report produced by the harness:

```bash
cat .cache/eval/swebench_harness/logs/run_evaluation/baseline-1-smoke/bedrock__us.amazon.nova-lite-v1:0/astropy__astropy-12907/report.json
```

For the 3-instance smoke slice:

```bash
uv run --package eval python -m eval.cli evaluate \
  --max-instances 3 \
  --predictions .cache/eval/runs/baseline-3.jsonl \
  --run-id baseline-3-smoke \
  --max-workers 1
```

### 6. Summarize A Completed Run

Once an evaluation has finished, you can print a compact summary without
opening the raw harness JSON files manually.

For the same single-instance run:

```bash
uv run --package eval python -m eval.cli summarize \
  --predictions .cache/eval/runs/baseline-1.jsonl \
  --run-id baseline-1-smoke
```

Expected output shape:

```text
Harness report: .cache/eval/swebench_harness/bedrock__us.amazon.nova-lite-v1:0.baseline-1-smoke.json
Run log directory: .cache/eval/swebench_harness/logs/run_evaluation/baseline-1-smoke/bedrock__us.amazon.nova-lite-v1:0
Total instances: 1
Submitted instances: 1
Completed instances: 1
Resolved instances: 0
Unresolved instances: 1
Empty patch instances: 0
Error instances: 0
Per-instance results:
- astropy__astropy-12907: unresolved
  patch applied: yes
  FAIL_TO_PASS: 0 passed, 2 failed
  PASS_TO_PASS failures: 0
  failing FAIL_TO_PASS test: astropy/modeling/tests/test_separable.py::...
```

This is meant to be a convenience layer over the official harness artifacts,
not a replacement for them. The raw JSON files are still the source of truth.

## Artifacts And Logs

### Harness Work Directory

By default the harness wrapper uses:

```text
.cache/eval/swebench_harness
```

You can override this with `--workdir`.

### Build Logs

Live-tailed build logs are discovered under:

```text
.cache/eval/swebench_harness/logs/build_images
```

Typical log files include:

- base image build logs
- environment image build logs
- instance image build logs
- instance preparation logs

### Prediction Files

The baseline generator writes JSONL to the path you pass via `--output`.

For example:

```text
.cache/eval/runs/baseline-1.jsonl
```

### Evaluation Reports

The official harness summary report is written in the harness work directory.

For example:

```text
.cache/eval/swebench_harness/bedrock__us.amazon.nova-lite-v1:0.baseline-1-smoke.json
```

Per-instance run logs and `report.json` files are written under:

```text
.cache/eval/swebench_harness/logs/run_evaluation/<run-id>/<model-name>/
```

## Troubleshooting

### Docker Endpoint Could Not Be Resolved

If `prepare-images` fails before the harness starts, check that the Docker CLI
can talk to your active daemon:

```bash
docker ps
docker context inspect
```

The wrapper resolves the Docker SDK endpoint from the current Docker context and
passes it through as `DOCKER_HOST`.

### Hugging Face Warnings About Unauthenticated Requests

Set:

```bash
export HUGGINGFACE_HUB_TOKEN=...
```

The wrapper will forward that value as `HF_TOKEN` for the harness if `HF_TOKEN`
is not already set.

### Bedrock Generation Fails Before Writing Any Predictions

Check that your AWS credentials and region are configured for Bedrock access:

```bash
aws sts get-caller-identity
echo "$AWS_DEFAULT_REGION"
```

If needed, pass an explicit Bedrock region:

```bash
uv run --package eval python -m eval.cli generate-baseline \
  --instance-id astropy__astropy-12907 \
  --region-name us-east-1 \
  --output .cache/eval/runs/baseline-1.jsonl
```

If you see an error saying that the model identifier is invalid, the most common
cause is that a region-specific foundation-model id was used where an inference
profile id is needed. The package default uses the US cross-region inference
profile form:

```text
bedrock/us.amazon.nova-lite-v1:0
```

Amazon Nova models commonly require an inference-profile id for `Converse`. For
example, `amazon.nova-lite-v1:0` may fail while `us.amazon.nova-lite-v1:0`
works.

If you previously ran the command with the older raw foundation-model id, rerun
with `--overwrite` or remove the previous output file first.

### Evaluation Fails Before Any Instance Runs

Check that:

- the predictions file exists
- the required SWE-bench images are already prepared
- Docker is reachable from the current shell

Useful checks:

```bash
docker ps
docker image inspect sweb.eval.x86_64.astropy__astropy-12907:latest >/dev/null && echo "image ready"
ls -l .cache/eval/runs/baseline-1.jsonl
```

### Summarize Cannot Find The Report

Check that:

- you are using the same `--run-id` that was passed to `evaluate`
- you are pointing at the same predictions file used for that run
- you are using the same harness `--workdir`

Useful checks:

```bash
ls -l .cache/eval/swebench_harness/*.json
find .cache/eval/swebench_harness/logs/run_evaluation -maxdepth 3 -type d
```

### The Command Succeeds Quickly But Nothing Is Rebuilt

That usually means the harness found the images already present and skipped the
build.

Check explicitly:

```bash
docker image inspect sweb.eval.x86_64.astropy__astropy-12907:latest
```

### A Build Appears Stuck

The harness can spend a while in base, environment, or instance image creation.
Inspect the logs under:

```text
.cache/eval/swebench_harness/logs/build_images
```

If the wrapper is running, it should also print newly discovered log file paths
and stream them live.
