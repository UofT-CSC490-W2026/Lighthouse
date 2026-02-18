"""S3 connector for pipeline artifact persistence."""

from __future__ import annotations

import re

import boto3


class S3Connector:
    """Small wrapper for writing pipeline artifacts to S3."""

    def __init__(self, *, region_name: str) -> None:
        self.region_name = region_name

    def upload_runtime_artifacts(
        self,
        *,
        bucket: str,
        repo_id: str,
        ref: str,
        job_id: str,
        manifest_bytes: bytes,
        chunks_bytes: bytes,
    ) -> str:
        """Upload runtime manifest/chunk artifacts and return key prefix."""
        client = boto3.client("s3", region_name=self.region_name)
        prefix = self._runtime_prefix(repo_id=repo_id, ref=ref, job_id=job_id)
        client.put_object(
            Bucket=bucket,
            Key=f"{prefix}/manifest.json",
            Body=manifest_bytes,
            ContentType="application/json",
        )
        client.put_object(
            Bucket=bucket,
            Key=f"{prefix}/chunks.jsonl",
            Body=chunks_bytes,
            ContentType="application/x-ndjson",
        )
        return prefix

    @staticmethod
    def _runtime_prefix(*, repo_id: str, ref: str, job_id: str) -> str:
        """Build sanitized runtime artifact key prefix."""
        repo_key = S3Connector._sanitize_identifier(repo_id.replace("/", "_"))
        ref_key = S3Connector._sanitize_identifier(ref)
        job_key = S3Connector._sanitize_identifier(job_id)
        return f"runtime-index/{repo_key}/{ref_key}/{job_key}"

    @staticmethod
    def _sanitize_identifier(value: str) -> str:
        """Normalize one path/key segment to a safe character set."""
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
        return normalized or "unknown"
