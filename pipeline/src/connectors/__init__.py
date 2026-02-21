"""Connector interfaces for pipeline integrations."""

from .github import GitHubConnector, GitHubTarballResult
from .milvus import MilvusConnector
from .postgres import PostgresConnector
from .s3 import S3Connector

__all__ = [
    "GitHubConnector",
    "GitHubTarballResult",
    "MilvusConnector",
    "PostgresConnector",
    "S3Connector",
]
