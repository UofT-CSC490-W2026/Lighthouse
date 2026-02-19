# Dataset Storage Conventions (Iteration 1)

This document defines the canonical S3 object-key layout for dataset pipeline outputs and the run manifest schema used for offline benchmark runs.

## Scope

- Applies to `OfflineDatasetWorkflow` in benchmark mode (iteration 1).
- Uses medallion-style layers (`bronze`, `silver`, `gold`) plus `manifests` and optional `quarantine`.
- Defines object-key conventions only. The S3 bucket itself is configured by `S3_BUCKET`.

## Canonical Offline Prefix

Base prefix for one offline benchmark run:

```text
offline-datasets/benchmark/dataset={dataset}/version={version}/run_id={run_id}
```

Where:

- `dataset`: sanitized dataset identifier (for example `swebench`)
- `version`: dataset snapshot/version (`latest` when omitted)
- `run_id`: workflow run/job identifier

## Canonical Offline Objects

Under each run prefix, artifacts are written to:

```text
{prefix}/manifests/run_manifest.json
{prefix}/bronze/records.jsonl
{prefix}/silver/records.jsonl
{prefix}/gold/dataset_instances.jsonl
{prefix}/quarantine/invalid_rows.jsonl      # optional
```

## Runtime Indexing Objects (Reference)

Runtime indexing artifacts remain under:

```text
runtime-index/{repo_key}/{ref_key}/{job_id}/manifest.json
runtime-index/{repo_key}/{ref_key}/{job_id}/chunks.jsonl
```

## Offline Run Manifest Schema (v1)

Manifest object location:

```text
{prefix}/manifests/run_manifest.json
```

Top-level schema:

```json
{
  "manifest_schema_version": "offline-run-manifest/v1",
  "workflow_type": "OfflineDatasetWorkflow",
  "status": "READY",
  "dataset_name": "swebench",
  "dataset_version": "v1",
  "workflow_id": "offline-datasets:swebench:v1",
  "run_id": "run_offline_001",
  "created_at_utc": "2026-02-19T17:20:00+00:00",
  "partitions": {
    "dataset": "swebench",
    "version": "v1",
    "run_id": "run_offline_001"
  },
  "metrics": {
    "records_in": 2294,
    "records_clean": 2260,
    "records_invalid": 34,
    "records_out": 2260
  },
  "artifacts": {
    "bronze": {"local_path": ".../offline_ingest_records.jsonl", "s3_key": ".../bronze/records.jsonl"},
    "silver": {"local_path": ".../offline_clean_records.jsonl", "s3_key": ".../silver/records.jsonl"},
    "gold": {"local_path": ".../offline_dataset_instances.jsonl", "s3_key": ".../gold/dataset_instances.jsonl"},
    "quarantine": {"local_path": ".../offline_quarantine_records.jsonl", "s3_key": ".../quarantine/invalid_rows.jsonl"},
    "manifest": {"local_path": ".../offline_manifest.json", "s3_key": ".../manifests/run_manifest.json"}
  },
  "storage": {
    "bucket": "example-bucket",
    "s3_key_prefix": "offline-datasets/benchmark/dataset=swebench/version=v1/run_id=run_offline_001"
  }
}
```

Field requirements:

- Required: `manifest_schema_version`, `workflow_type`, `status`, `dataset_name`, `workflow_id`, `run_id`, `created_at_utc`, `partitions`, `metrics`, `artifacts`, `storage`.
- Optional: `dataset_version` (falls back to `latest` in partition), `artifacts.quarantine.local_path` and `artifacts.quarantine.s3_key`.
- `status` is run terminal status from the pipeline perspective for this manifest snapshot (iteration 1 emits `READY` on successful store stage).
