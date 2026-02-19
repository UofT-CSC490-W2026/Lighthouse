# Lighthouse Data Pipeline Service

This directory contains the standalone data pipeline/ingestion worker service.

## Responsibilities

- Execute runtime indexing workflows
- Execute offline dataset ingestion workflows
- Execute mental-model update workflows
- Report index lifecycle states (`NOT_FOUND`, `PENDING`, `READY`, `FAILED`, `STALE`)

## Setup

```bash
cd pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run worker

```bash
set -a
source .env
set +a
# ensure persistence tables are present
alembic -c alembic.ini upgrade head
python -m src.worker
```

## Trigger offline ingestion (manual)

Start one `OfflineDatasetWorkflow` run for a pinned benchmark snapshot:

```bash
set -a
source .env
set +a
python -m src.offline_trigger \
  --dataset-name swebench \
  --dataset-version v1 \
  --dataset-source-path /absolute/path/to/swebench-v1.jsonl \
  --trigger manual \
  --requested-by operator_cli
```

Start one incremental rolling issue->PR->diff ingestion run:

```bash
set -a
source .env
set +a
python -m src.offline_trigger \
  --dataset-name issue_pr_diff \
  --dataset-version rolling-live \
  --dataset-source-path /absolute/path/to/issue_pr_diff.jsonl \
  --watermark-start 2026-02-01T00:00:00Z \
  --watermark-end 2026-02-02T00:00:00Z \
  --max-records 5000 \
  --source-cursor gharchive:2026-02-02 \
  --trigger daily_schedule \
  --requested-by operator_cli
```

Optional:

- `--force-reingest` to bypass canonical idempotency and start a unique rerun.
- `--source-event-id <id>` when the trigger is from an external release event.
- `--watermark-start`, `--watermark-end`, `--max-records`, and `--source-cursor` to bound incremental rolling scraped runs.

## Schedule monthly evaluation refresh

Create or reuse a monthly `EvaluationRefreshWorkflow` for a pinned benchmark snapshot:

```bash
set -a
source .env
set +a
python -m src.evaluation_refresh_trigger \
  --dataset-name swebench \
  --dataset-version v1 \
  --cron-schedule "0 0 1 * *" \
  --trigger monthly_schedule \
  --requested-by operator_cli
```

Notes:

- Workflow id is canonical per dataset/version (`evaluation-refresh:{dataset}:{version}:monthly`).
- Re-running the command reuses existing schedule wiring instead of duplicating it.
- Each monthly run computes baseline fail-to-pass and regression rates and persists metrics in `quality_metrics`.

## Docker

Build (from repository root so the shared package is included):

```bash
docker build -f pipeline/Dockerfile -t lighthouse-pipeline:dev .
```

Run:

```bash
docker run --rm --env-file pipeline/.env lighthouse-pipeline:dev
```
