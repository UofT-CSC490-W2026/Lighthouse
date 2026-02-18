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
python -m src.worker
```

## Docker

Build (from repository root so the shared package is included):

```bash
docker build -f pipeline/Dockerfile -t lighthouse-pipeline:dev .
```

Run:

```bash
docker run --rm --env-file pipeline/.env lighthouse-pipeline:dev
```
