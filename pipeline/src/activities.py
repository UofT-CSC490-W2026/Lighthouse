"""Temporal activities for the standalone pipeline worker."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import re
from pathlib import Path
import tarfile
from typing import Any
from urllib.parse import urlparse
from git import Repo
from temporalio import activity

from .config import settings
from .connectors import GitHubConnector, S3Connector
from .contracts import IndexStage
from .persistence import (
    record_runtime_index_failed,
    record_runtime_index_progress,
    record_runtime_index_ready,
    record_runtime_index_started,
)

_MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
_MAX_FILE_BYTES = 256 * 1024
_MAX_FILE_COUNT = 1500
_MAX_TOTAL_TEXT_BYTES = 12 * 1024 * 1024
_CHUNK_SIZE_CHARS = 1200
_CHUNK_OVERLAP_CHARS = 200
_MIN_CHUNK_CHARS = 120

_SKIP_PREFIXES = (
    ".git/",
    ".hg/",
    ".svn/",
    ".venv/",
    "venv/",
    "node_modules/",
    "__pycache__/",
    ".mypy_cache/",
    ".pytest_cache/",
    "build/",
    "dist/",
    ".idea/",
    ".vscode/",
)
_SUPPORTED_SUFFIXES = {
    ".c",
    ".cfg",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".md",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
_SUPPORTED_FILENAMES = {
    "Dockerfile",
    "Makefile",
    "README",
    "README.md",
    "go.mod",
    "go.sum",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
}
_GITHUB_CONNECTOR = GitHubConnector()
_S3_CONNECTOR = S3Connector(region_name=settings.aws_region)


@activity.defn(name="ingest_activity")
async def ingest_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Ingest raw source inputs for the current workflow payload."""
    if not _is_runtime_payload(payload):
        return {"stage": "ingest", "ok": True, "payload": payload}

    repo_id = _require_str(payload, "repo_id")
    repo_url = _require_str(payload, "repo_url")
    ref = _coerce_ref(payload.get("ref"))
    artifact_dir = _runtime_artifact_dir(payload)
    ingest_path = artifact_dir / "ingest_files.jsonl"

    snapshot_sha, files = _load_repo_files(repo_url=repo_url, ref=ref, payload=payload)
    _write_jsonl(ingest_path, files)

    return {
        **payload,
        "stage": "ingest",
        "ok": True,
        "repo_id": repo_id,
        "ref": ref,
        "snapshot_sha": snapshot_sha,
        "artifact_dir": str(artifact_dir),
        "ingest_path": str(ingest_path),
        "ingest_stats": {
            "file_count": len(files),
            "total_text_bytes": sum(item["size_bytes"] for item in files),
        },
    }


@activity.defn(name="clean_activity")
async def clean_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Clean and normalize ingested payload artifacts."""
    if not _is_runtime_payload(payload):
        return {"stage": "clean", "ok": True, "payload": payload}

    ingest_path = Path(_require_str(payload, "ingest_path"))
    artifact_dir = Path(_require_str(payload, "artifact_dir"))
    clean_path = artifact_dir / "clean_documents.jsonl"

    seen_paths: set[str] = set()
    cleaned_docs: list[dict[str, Any]] = []
    dropped_records = 0
    for record in _read_jsonl(ingest_path):
        path = str(record.get("path") or "").strip()
        content = str(record.get("content") or "")
        if not path or path in seen_paths:
            dropped_records += 1
            continue
        normalized = _normalize_source_text(content)
        if not normalized:
            dropped_records += 1
            continue
        seen_paths.add(path)
        cleaned_docs.append(
            {
                "path": path,
                "content": normalized,
                "size_bytes": len(normalized.encode("utf-8")),
                "line_count": normalized.count("\n") + 1,
                "language": _infer_language(path),
            }
        )

    _write_jsonl(clean_path, cleaned_docs)
    return {
        **payload,
        "stage": "clean",
        "ok": True,
        "clean_path": str(clean_path),
        "clean_stats": {
            "input_file_count": len(seen_paths) + dropped_records,
            "document_count": len(cleaned_docs),
            "dropped_records": dropped_records,
        },
    }


@activity.defn(name="transform_activity")
async def transform_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Transform cleaned inputs into retrieval/evaluation ready structures."""
    if not _is_runtime_payload(payload):
        return {"stage": "transform", "ok": True, "payload": payload}

    repo_id = _require_str(payload, "repo_id")
    ref = _coerce_ref(payload.get("ref"))
    clean_path = Path(_require_str(payload, "clean_path"))
    artifact_dir = Path(_require_str(payload, "artifact_dir"))
    transform_path = artifact_dir / "transform_chunks.jsonl"

    chunks: list[dict[str, Any]] = []
    chunk_digest = hashlib.sha1()
    for doc in _read_jsonl(clean_path):
        path = str(doc.get("path") or "")
        content = str(doc.get("content") or "")
        if not path or not content:
            continue
        for index, start, end, text in _chunk_text(
            content=content,
            chunk_size=_CHUNK_SIZE_CHARS,
            overlap=_CHUNK_OVERLAP_CHARS,
            min_chunk_size=_MIN_CHUNK_CHARS,
        ):
            chunk_id = hashlib.sha1(
                f"{repo_id}:{ref}:{path}:{index}:{start}:{end}".encode("utf-8")
            ).hexdigest()
            text_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()
            chunk_digest.update(text_hash.encode("utf-8"))
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "repo_id": repo_id,
                    "ref": ref,
                    "path": path,
                    "chunk_index": index,
                    "start_char": start,
                    "end_char": end,
                    "text": text,
                    "text_hash": text_hash,
                }
            )

    _write_jsonl(transform_path, chunks)
    return {
        **payload,
        "stage": "transform",
        "ok": True,
        "transform_path": str(transform_path),
        "transform_stats": {
            "chunk_count": len(chunks),
            "chunk_chars_total": sum(len(chunk["text"]) for chunk in chunks),
            "corpus_hash": chunk_digest.hexdigest(),
        },
    }


@activity.defn(name="store_activity")
async def store_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist transformed artifacts to configured storage backends."""
    if not _is_runtime_payload(payload):
        return {"stage": "store", "ok": True, "payload": payload}

    artifact_dir = Path(_require_str(payload, "artifact_dir"))
    transform_path = Path(_require_str(payload, "transform_path"))
    repo_id = _require_str(payload, "repo_id")
    ref = _coerce_ref(payload.get("ref"))
    job_id = _require_str(payload, "job_id")
    workflow_id = _require_str(payload, "workflow_id")

    snapshot_sha = _resolve_snapshot_sha(
        payload.get("snapshot_sha"),
        corpus_hash=(payload.get("transform_stats") or {}).get("corpus_hash"),
    )
    manifest_path = artifact_dir / "manifest.json"
    manifest = {
        "repo_id": repo_id,
        "ref": ref,
        "job_id": job_id,
        "workflow_id": workflow_id,
        "snapshot_sha": snapshot_sha,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ingest_stats": payload.get("ingest_stats"),
        "clean_stats": payload.get("clean_stats"),
        "transform_stats": payload.get("transform_stats"),
        "transform_path": str(transform_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    s3_key_prefix = _maybe_store_runtime_artifacts_to_s3(
        manifest_path=manifest_path,
        chunks_path=transform_path,
        repo_id=repo_id,
        ref=ref,
        job_id=job_id,
    )

    return {
        **payload,
        "stage": "store",
        "ok": True,
        "snapshot_sha": snapshot_sha,
        "artifact_manifest_path": str(manifest_path),
        "artifact_chunks_path": str(transform_path),
        "store_stats": {
            "s3_key_prefix": s3_key_prefix,
        },
    }


@activity.defn(name="mental_model_activity")
async def mental_model_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Build or refresh mental-model artifacts for a repository scope."""
    return {"stage": "mental_model", "ok": True, "payload": payload}


@activity.defn(name="persist_runtime_index_start_activity")
async def persist_runtime_index_start_activity(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist initial runtime index job/state records at workflow start."""
    await record_runtime_index_started(
        job_id=_require_str(payload, "job_id"),
        workflow_id=_require_str(payload, "workflow_id"),
        repo_id=_require_str(payload, "repo_id"),
        ref=_require_str(payload, "ref"),
    )
    return {"stage": "persist_start", "ok": True, "job_id": payload["job_id"]}


@activity.defn(name="persist_runtime_index_success_activity")
async def persist_runtime_index_success_activity(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist terminal READY state for a completed runtime index run."""
    await record_runtime_index_ready(
        job_id=_require_str(payload, "job_id"),
        workflow_id=_require_str(payload, "workflow_id"),
        repo_id=_require_str(payload, "repo_id"),
        ref=_require_str(payload, "ref"),
        snapshot_sha=payload.get("snapshot_sha"),
    )
    return {"stage": "persist_success", "ok": True, "job_id": payload["job_id"]}


@activity.defn(name="persist_runtime_index_failure_activity")
async def persist_runtime_index_failure_activity(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist terminal FAILED state and error metadata for runtime indexing."""
    stage_raw = payload.get("stage")
    stage = IndexStage(stage_raw) if stage_raw else None
    await record_runtime_index_failed(
        job_id=_require_str(payload, "job_id"),
        workflow_id=_require_str(payload, "workflow_id"),
        repo_id=_require_str(payload, "repo_id"),
        ref=_require_str(payload, "ref"),
        stage=stage,
        error_code=_require_str(payload, "error_code"),
        error_message=_require_str(payload, "error_message"),
        progress_pct=_require_progress(payload, "progress_pct"),
    )
    return {"stage": "persist_failure", "ok": True, "job_id": payload["job_id"]}


@activity.defn(name="persist_runtime_index_progress_activity")
async def persist_runtime_index_progress_activity(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist in-flight stage and progress updates for runtime indexing."""
    stage = IndexStage(_require_str(payload, "stage"))
    progress = _require_progress(payload, "progress_pct")
    await record_runtime_index_progress(
        job_id=_require_str(payload, "job_id"),
        workflow_id=_require_str(payload, "workflow_id"),
        repo_id=_require_str(payload, "repo_id"),
        ref=_require_str(payload, "ref"),
        stage=stage,
        progress_pct=progress,
    )
    return {
        "stage": "persist_progress",
        "ok": True,
        "job_id": payload["job_id"],
        "progress_pct": progress,
    }


def _require_str(payload: dict[str, Any], key: str) -> str:
    """Read and validate a required non-empty string payload field."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"payload field '{key}' is required")
    return value


def _require_progress(payload: dict[str, Any], key: str) -> int:
    """Read and validate a required integer progress field in `[0, 100]`."""
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"payload field '{key}' must be an integer")
    if value < 0 or value > 100:
        raise ValueError(f"payload field '{key}' must be between 0 and 100")
    return value


def _is_runtime_payload(payload: dict[str, Any]) -> bool:
    """Return true when payload corresponds to runtime repo indexing."""
    repo_id = payload.get("repo_id")
    repo_url = payload.get("repo_url")
    return isinstance(repo_id, str) and isinstance(repo_url, str)


def _coerce_ref(value: Any) -> str:
    """Normalize git ref value to a non-empty string."""
    if not isinstance(value, str):
        return "main"
    normalized = value.strip()
    return normalized or "main"


def _runtime_artifact_dir(payload: dict[str, Any]) -> Path:
    """Build the runtime activity artifact directory for this job."""
    job_id = _require_str(payload, "job_id")
    base_dir = Path(__file__).resolve().parents[1] / ".artifacts" / "runtime_index"
    artifact_dir = base_dir / _sanitize_identifier(job_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def _sanitize_identifier(value: str) -> str:
    """Produce a filesystem-safe identifier segment."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned or "unknown"


def _load_repo_files(
    *,
    repo_url: str,
    ref: str,
    payload: dict[str, Any],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Load repository source files from GitHub tarball or local path."""
    owner_repo = _GITHUB_CONNECTOR.parse_owner_repo(repo_url)
    token = _resolve_github_token(payload)
    if owner_repo is not None:
        owner, repo = owner_repo
        tarball = _GITHUB_CONNECTOR.fetch_tarball(
            owner=owner,
            repo=repo,
            ref=ref,
            token=token,
        )
        files = _extract_tarball_files(tarball.archive_bytes)
        return tarball.snapshot_sha, files
    local_path = _parse_local_repo_path(repo_url)
    if local_path is None:
        raise ValueError(
            "repo_url must be a GitHub URL/SSH reference or an accessible local path"
        )
    return _load_local_files(local_path=local_path, ref=ref)


def _extract_tarball_files(archive_bytes: bytes) -> list[dict[str, Any]]:
    """Extract, filter, and decode source files from tarball archive bytes."""
    if len(archive_bytes) > _MAX_ARCHIVE_BYTES:
        raise ValueError(
            f"repository archive exceeds max supported size ({_MAX_ARCHIVE_BYTES} bytes)"
        )

    files: list[dict[str, Any]] = []
    total_bytes = 0
    with tarfile.open(fileobj=BytesIO(archive_bytes), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            path = _normalize_archive_path(member.name)
            if not _should_index_path(path):
                continue
            if member.size <= 0 or member.size > _MAX_FILE_BYTES:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            raw = extracted.read(_MAX_FILE_BYTES + 1)
            if len(raw) > _MAX_FILE_BYTES or _looks_binary(raw):
                continue
            text = raw.decode("utf-8", errors="ignore")
            if not text.strip():
                continue
            encoded_size = len(text.encode("utf-8"))
            if total_bytes + encoded_size > _MAX_TOTAL_TEXT_BYTES:
                break
            files.append(
                {
                    "path": path,
                    "content": text,
                    "size_bytes": encoded_size,
                    "language": _infer_language(path),
                }
            )
            total_bytes += encoded_size
            if len(files) >= _MAX_FILE_COUNT:
                break
    return files


def _normalize_archive_path(path: str) -> str:
    """Strip tarball root directory and normalize path separators."""
    normalized = path.replace("\\", "/").lstrip("./")
    if "/" not in normalized:
        return normalized
    return normalized.split("/", 1)[1]


def _parse_local_repo_path(repo_url: str) -> Path | None:
    """Resolve a local repository path from `repo_url` format."""
    parsed = urlparse(repo_url)
    if parsed.scheme in {"", "file"}:
        candidate = Path(
            parsed.path if parsed.scheme == "file" else repo_url
        ).expanduser()
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _load_local_files(
    local_path: Path, ref: str
) -> tuple[str | None, list[dict[str, Any]]]:
    """Read indexable source files from a local repository checkout."""
    snapshot_sha = _resolve_local_snapshot_sha(local_path, ref)
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for file_path in local_path.rglob("*"):
        if not file_path.is_file():
            continue
        rel_path = file_path.relative_to(local_path).as_posix()
        if not _should_index_path(rel_path):
            continue
        size = file_path.stat().st_size
        if size <= 0 or size > _MAX_FILE_BYTES:
            continue
        raw = file_path.read_bytes()
        if _looks_binary(raw):
            continue
        text = raw.decode("utf-8", errors="ignore")
        if not text.strip():
            continue
        encoded_size = len(text.encode("utf-8"))
        if total_bytes + encoded_size > _MAX_TOTAL_TEXT_BYTES:
            break
        files.append(
            {
                "path": rel_path,
                "content": text,
                "size_bytes": encoded_size,
                "language": _infer_language(rel_path),
            }
        )
        total_bytes += encoded_size
        if len(files) >= _MAX_FILE_COUNT:
            break
    return snapshot_sha, files


def _resolve_local_snapshot_sha(local_path: Path, ref: str) -> str | None:
    """Resolve local git commit SHA for the requested ref when available."""
    try:
        repo = Repo(local_path)
        return repo.commit(ref).hexsha
    except Exception:
        return None


def _resolve_github_token(payload: dict[str, Any]) -> str | None:
    """Resolve optional GitHub token from payload then pipeline settings."""
    payload_token = payload.get("github_token")
    if isinstance(payload_token, str) and payload_token.strip():
        return payload_token.strip()
    if settings.github_read_token is not None:
        configured = settings.github_read_token.get_secret_value().strip()
        if configured:
            return configured
    return None


def _should_index_path(path: str) -> bool:
    """Return true when a repository path should be indexed."""
    normalized = path.replace("\\", "/").lstrip("./")
    if not normalized:
        return False
    lower_path = normalized.lower()
    for prefix in _SKIP_PREFIXES:
        if lower_path.startswith(prefix.lower()) or f"/{prefix.lower()}" in lower_path:
            return False
    name = Path(normalized).name
    suffix = Path(normalized).suffix.lower()
    return suffix in _SUPPORTED_SUFFIXES or name in _SUPPORTED_FILENAMES


def _looks_binary(raw: bytes) -> bool:
    """Detect binary-like payloads using null-byte heuristics."""
    return b"\x00" in raw[:4096]


def _normalize_source_text(text: str) -> str:
    """Normalize source text while preserving useful formatting boundaries."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]

    cleaned_lines: list[str] = []
    blank_run = 0
    for line in lines:
        if line:
            blank_run = 0
            cleaned_lines.append(line)
            continue
        blank_run += 1
        if blank_run <= 2:
            cleaned_lines.append("")

    cleaned = "\n".join(cleaned_lines).strip()
    if len(cleaned) < 20:
        return ""
    return cleaned


def _chunk_text(
    *,
    content: str,
    chunk_size: int,
    overlap: int,
    min_chunk_size: int,
) -> Iterable[tuple[int, int, int, str]]:
    """Yield overlapping text chunks as `(index, start, end, text)` tuples."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be in [0, chunk_size)")

    cursor = 0
    index = 0
    content_len = len(content)
    while cursor < content_len:
        end = min(content_len, cursor + chunk_size)
        text = content[cursor:end].strip()
        if len(text) >= min_chunk_size:
            yield index, cursor, end, text
            index += 1
        if end >= content_len:
            break
        cursor = end - overlap


def _infer_language(path: str) -> str | None:
    """Map filename suffixes to a coarse language identifier."""
    suffix = Path(path).suffix.lower()
    mappings = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".java": "java",
        ".rb": "ruby",
        ".rs": "rust",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "c",
        ".hpp": "cpp",
        ".cs": "csharp",
        ".kt": "kotlin",
        ".swift": "swift",
        ".php": "php",
        ".sql": "sql",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".sh": "shell",
    }
    return mappings.get(suffix)


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    """Write newline-delimited JSON records to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    """Read newline-delimited JSON records from disk."""
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _resolve_snapshot_sha(snapshot_sha: Any, *, corpus_hash: Any) -> str:
    """Resolve snapshot SHA, falling back to corpus hash-derived identifier."""
    if isinstance(snapshot_sha, str) and snapshot_sha.strip():
        return snapshot_sha.strip()
    if isinstance(corpus_hash, str) and corpus_hash.strip():
        return f"content-{corpus_hash.strip()[:40]}"
    return "content-unknown"


def _maybe_store_runtime_artifacts_to_s3(
    *,
    manifest_path: Path,
    chunks_path: Path,
    repo_id: str,
    ref: str,
    job_id: str,
) -> str | None:
    """Optionally upload runtime artifacts to S3 when bucket config is set."""
    bucket = settings.s3_bucket
    if not bucket:
        return None

    try:
        return _S3_CONNECTOR.upload_runtime_artifacts(
            bucket=bucket,
            repo_id=repo_id,
            ref=ref,
            job_id=job_id,
            manifest_bytes=manifest_path.read_bytes(),
            chunks_bytes=chunks_path.read_bytes(),
        )
    except Exception:
        return None
