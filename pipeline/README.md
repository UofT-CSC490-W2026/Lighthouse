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

## Trigger offline benchmark ingestion (manual)

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

Optional:

- `--force-reingest` to bypass canonical idempotency and start a unique rerun.
- `--source-event-id <id>` when the trigger is from an external release event.

## Docker

Build (from repository root so the shared package is included):

```bash
docker build -f pipeline/Dockerfile -t lighthouse-pipeline:dev .
```

Run:

```bash
docker run --rm --env-file pipeline/.env lighthouse-pipeline:dev
```
