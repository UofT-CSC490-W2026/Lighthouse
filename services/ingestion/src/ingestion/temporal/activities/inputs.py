from __future__ import annotations

from dataclasses import dataclass, field
from shared.config import DEFAULT_EMBEDDING_STRATEGY

EMBED_BATCH_SIZE = 512


# --- Activity-level input / output dataclasses ---


@dataclass
class EnsureRepoInput:
    github_repo_id: int
    repo_url: str
    full_name: str


@dataclass
class UpdateBranchStatusInput:
    repository_id: str
    branch: str
    status: str
    latest_commit: str | None = None
    github_token: str | None = None


@dataclass
class GitCloneFetchInput:
    repo_url: str
    repo_dir_name: str
    branch: str
    github_token: str | None = None


@dataclass
class GitCloneFetchOutput:
    repo_path: str
    latest_commit: str


@dataclass
class ChunkFilesInput:
    repo_path: str
    repository_id: str
    branch: str
    chunker_strategy: str = "sliding_window"
    file_filter: list[str] | None = None


@dataclass
class ChunkFilesOutput:
    batch_id: str
    chunk_count: int


@dataclass
class GetChangedFilesInput:
    repo_path: str
    before_commit: str
    after_commit: str


@dataclass
class DeleteChunksInput:
    repository_id: str
    branch: str


@dataclass
class DeleteChunksForFilesInput:
    repository_id: str
    branch: str
    file_paths: list[str] = field(default_factory=list)


@dataclass
class EmbedBatchInput:
    batch_id: str
    offset: int
    limit: int
    embedding_strategy: str = DEFAULT_EMBEDDING_STRATEGY


@dataclass
class StoreChunksInput:
    batch_id: str


@dataclass
class CleanupStagingInput:
    batch_id: str


# --- Workflow-level input dataclasses (used by main.py to start workflows) ---


@dataclass
class IndexRepoInput:
    github_repo_id: int
    repo_url: str
    full_name: str
    branches: list[str]
    github_token: str | None = None
    embedding_strategy: str = DEFAULT_EMBEDDING_STRATEGY


@dataclass
class IndexBranchInput:
    repository_id: str
    github_repo_id: int
    repo_url: str
    full_name: str
    branch: str
    github_token: str | None = None
    chunker_strategy: str = "sliding_window"
    embedding_strategy: str = DEFAULT_EMBEDDING_STRATEGY


@dataclass
class IncrementalIndexInput:
    github_repo_id: int
    full_name: str
    branch: str
    before_commit: str
    after_commit: str
    embedding_strategy: str = DEFAULT_EMBEDDING_STRATEGY
