"""S3 connector for pipeline artifact persistence."""

from __future__ import annotations

import re
from typing import Mapping

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

    def check_bucket_access(self, *, bucket: str) -> None:
        """Validate S3 bucket reachability and permissions."""
        client = boto3.client("s3", region_name=self.region_name)
        client.head_bucket(Bucket=bucket)

    def upload_offline_benchmark_artifacts(
        self,
        *,
        bucket: str,
        dataset_name: str,
        dataset_version: str | None,
        job_id: str,
        artifacts: Mapping[str, bytes],
    ) -> str:
        """Upload offline benchmark artifacts and return stored S3 prefix."""
        client = boto3.client("s3", region_name=self.region_name)
        version_key = self._sanitize_identifier(dataset_version or "latest")
        prefix = (
            "offline-datasets/benchmark/"
            f"{self._sanitize_identifier(dataset_name)}/"
            f"{version_key}/"
            f"{self._sanitize_identifier(job_id)}"
        )
        for filename, data in artifacts.items():
            if filename.endswith(".jsonl"):
                content_type = "application/x-ndjson"
            else:
                content_type = "application/json"
            client.put_object(
                Bucket=bucket,
                Key=f"{prefix}/{filename}",
                Body=data,
                ContentType=content_type,
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
