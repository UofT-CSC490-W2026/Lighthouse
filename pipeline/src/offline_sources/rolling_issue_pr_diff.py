"""Incremental rolling issue->PR->diff source adapter for offline ingest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

_SUPPORTED_SUFFIXES = {".json", ".jsonl"}
_JSON_RECORD_KEYS = ("records", "data", "items")
_VERSION_RECORD_KEYS = ("dataset_version", "version")
_TIMESTAMP_KEYS = (
    "event_ts",
    "event_time",
    "updated_at",
    "merged_at",
    "created_at",
)
_DEFAULT_SOURCE_FILENAMES = (
    "issue_pr_diff.jsonl",
    "issue_pr_diff.json",
    "records.jsonl",
    "records.json",
    "events.jsonl",
    "events.json",
)


@dataclass(frozen=True, slots=True)
class RollingIssuePrDiffSnapshot:
    """Loaded rolling issue/PR/diff records and source metadata."""

    dataset_version: str
    source_path: str
    source_mode: str
    source_format: str
    snapshot_sha256: str
    snapshot_size_bytes: int
    raw_record_count: int
    filtered_record_count: int
    watermark_start: str | None
    watermark_end: str | None
    records: list[dict[str, Any]]


class RollingIssuePrDiffAdapter:
    """Load and bound rolling issue/PR/diff records for incremental runs."""

    def load_snapshot(
        self,
        *,
        dataset_version: str,
        dataset_source_path: str,
        watermark_start: str | None = None,
        watermark_end: str | None = None,
        max_records: int | None = None,
    ) -> RollingIssuePrDiffSnapshot:
        """Load one rolling source snapshot and apply optional bounds/dedupe."""
        version = self._validate_version(dataset_version)
        requested_path = self._resolve_input_path(dataset_source_path)
        source_mode = "directory_path" if requested_path.is_dir() else "file_path"
        source_path = self._resolve_source_file(requested_path)
        source_format = source_path.suffix.lower().lstrip(".")

        snapshot_bytes = source_path.read_bytes()
        snapshot_sha256 = hashlib.sha256(snapshot_bytes).hexdigest()
        records = self._parse_records(source_path=source_path)
        self._validate_record_versions(records=records, dataset_version=version)

        bounded_records = self._apply_incremental_bounds(
            records=records,
            watermark_start=watermark_start,
            watermark_end=watermark_end,
            max_records=max_records,
        )
        return RollingIssuePrDiffSnapshot(
            dataset_version=version,
            source_path=str(source_path),
            source_mode=source_mode,
            source_format=source_format,
            snapshot_sha256=snapshot_sha256,
            snapshot_size_bytes=len(snapshot_bytes),
            raw_record_count=len(records),
            filtered_record_count=len(bounded_records),
            watermark_start=_normalize_timestamp_string(watermark_start),
            watermark_end=_normalize_timestamp_string(watermark_end),
            records=bounded_records,
        )

    def _validate_version(self, dataset_version: str) -> str:
        """Validate explicit dataset version label for rolling snapshots."""
        normalized = dataset_version.strip()
        if not normalized:
            raise ValueError("dataset_version is required for rolling issue/pr snapshots")
        return normalized

    def _resolve_input_path(self, dataset_source_path: str) -> Path:
        """Resolve and validate source path for rolling snapshot loading."""
        source_path = dataset_source_path.strip()
        if not source_path:
            raise ValueError("dataset_source_path is required for rolling snapshots")
        path = Path(source_path).expanduser()
        if not path.exists():
            raise ValueError(f"dataset_source_path does not exist: {path}")
        return path.resolve()

    def _resolve_source_file(self, requested_path: Path) -> Path:
        """Resolve one concrete JSON/JSONL source file for rolling records."""
        if requested_path.is_file():
            self._validate_file_extension(requested_path)
            return requested_path

        if not requested_path.is_dir():
            raise ValueError(
                "dataset_source_path must be a file or directory "
                f"(received: {requested_path})"
            )

        for filename in _DEFAULT_SOURCE_FILENAMES:
            candidate = requested_path / filename
            if candidate.is_file():
                return candidate.resolve()

        supported_files = sorted(
            path
            for path in requested_path.iterdir()
            if path.is_file() and path.suffix.lower() in _SUPPORTED_SUFFIXES
        )
        if not supported_files:
            raise ValueError(
                "Could not resolve a rolling issue/pr snapshot file in directory "
                f"{requested_path}"
            )
        return supported_files[0].resolve()

    def _validate_file_extension(self, path: Path) -> None:
        """Ensure rolling snapshot source file extension is supported."""
        suffix = path.suffix.lower()
        if suffix not in _SUPPORTED_SUFFIXES:
            raise ValueError(
                "Rolling issue/pr snapshot file must be .json or .jsonl "
                f"(received: {path})"
            )

    def _parse_records(self, *, source_path: Path) -> list[dict[str, Any]]:
        """Parse records from one JSON/JSONL source file."""
        suffix = source_path.suffix.lower()
        if suffix == ".jsonl":
            return self._parse_jsonl_records(source_path)
        if suffix == ".json":
            return self._parse_json_records(source_path)
        raise ValueError(
            "Rolling issue/pr snapshot file must be .json or .jsonl "
            f"(received: {source_path})"
        )

    def _parse_jsonl_records(self, source_path: Path) -> list[dict[str, Any]]:
        """Parse object records from JSONL source file."""
        records: list[dict[str, Any]] = []
        with source_path.open("r", encoding="utf-8") as handle:
            for line_index, line in enumerate(handle, start=1):
                value = line.strip()
                if not value:
                    continue
                parsed = json.loads(value)
                if not isinstance(parsed, dict):
                    raise ValueError(
                        "Rolling JSONL record at line "
                        f"{line_index} must be an object"
                    )
                records.append(parsed)
        return records

    def _parse_json_records(self, source_path: Path) -> list[dict[str, Any]]:
        """Parse object records from JSON source file."""
        parsed = json.loads(source_path.read_text(encoding="utf-8"))
        if isinstance(parsed, list):
            return self._validate_record_list(parsed, context="json list")
        if isinstance(parsed, dict):
            for key in _JSON_RECORD_KEYS:
                value = parsed.get(key)
                if isinstance(value, list):
                    return self._validate_record_list(
                        value,
                        context=f"json key '{key}'",
                    )
        raise ValueError(
            "Rolling JSON source must be a list of records or object containing "
            f"one of keys: {', '.join(_JSON_RECORD_KEYS)}"
        )

    def _validate_record_list(
        self,
        records: list[Any],
        *,
        context: str,
    ) -> list[dict[str, Any]]:
        """Validate that each parsed record is an object."""
        normalized: list[dict[str, Any]] = []
        for record_index, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError(
                    "Rolling record in "
                    f"{context} at index {record_index} must be an object"
                )
            normalized.append(record)
        return normalized

    def _validate_record_versions(
        self,
        *,
        records: list[dict[str, Any]],
        dataset_version: str,
    ) -> None:
        """Reject records carrying conflicting explicit version fields."""
        for record_index, record in enumerate(records):
            for key in _VERSION_RECORD_KEYS:
                value = record.get(key)
                if value is None:
                    continue
                normalized = str(value).strip()
                if not normalized:
                    continue
                if normalized != dataset_version:
                    raise ValueError(
                        "Rolling snapshot contains mismatched "
                        f"{key} at record index {record_index}: "
                        f"{normalized} != {dataset_version}"
                    )

    def _apply_incremental_bounds(
        self,
        *,
        records: list[dict[str, Any]],
        watermark_start: str | None,
        watermark_end: str | None,
        max_records: int | None,
    ) -> list[dict[str, Any]]:
        """Apply watermark filtering, deterministic dedupe, and optional cap."""
        start = _parse_optional_timestamp(watermark_start)
        end = _parse_optional_timestamp(watermark_end)
        if start is not None and end is not None and start > end:
            raise ValueError("watermark_start must be <= watermark_end")

        if max_records is not None and max_records <= 0:
            raise ValueError("max_records must be positive when provided")

        deduped: dict[str, tuple[datetime | None, int, dict[str, Any]]] = {}
        for index, record in enumerate(records):
            event_ts = _extract_event_timestamp(record)
            if start is not None and event_ts is not None and event_ts < start:
                continue
            if end is not None and event_ts is not None and event_ts > end:
                continue

            dedupe_key = _rolling_chain_key(record, fallback_index=index)
            existing = deduped.get(dedupe_key)
            if existing is None:
                deduped[dedupe_key] = (event_ts, index, record)
                continue
            existing_ts, existing_index, _ = existing
            if _is_candidate_newer(
                current_ts=event_ts,
                current_index=index,
                existing_ts=existing_ts,
                existing_index=existing_index,
            ):
                deduped[dedupe_key] = (event_ts, index, record)

        ordered = sorted(
            deduped.values(),
            key=lambda entry: (
                entry[0] or datetime.fromtimestamp(0, tz=timezone.utc),
                entry[1],
            ),
        )
        if max_records is not None:
            ordered = ordered[-max_records:]
        return [record for (_, _, record) in ordered]


def _rolling_chain_key(record: dict[str, Any], *, fallback_index: int) -> str:
    """Build deterministic chain-level dedupe key for rolling records."""
    explicit = _coerce_text(
        record.get("chain_id")
        or record.get("instance_id")
        or record.get("event_id")
    )
    if explicit:
        return explicit

    repo_id = _normalize_repo_id(
        _coerce_text(
            record.get("repo_id")
            or record.get("repo")
            or record.get("repository")
            or record.get("repository_full_name")
        )
    )
    issue_number = _normalize_number_token(record.get("issue_number"))
    pr_number = _normalize_number_token(record.get("pr_number"))
    if repo_id and issue_number and pr_number:
        return f"{repo_id}#{issue_number}:{pr_number}"
    if repo_id and pr_number:
        return f"{repo_id}:pr:{pr_number}"
    if repo_id and issue_number:
        return f"{repo_id}:issue:{issue_number}"

    fallback_seed = json.dumps(record, ensure_ascii=True, sort_keys=True)
    digest = hashlib.sha1(fallback_seed.encode("utf-8")).hexdigest()[:20]
    return f"fallback-{fallback_index}-{digest}"


def _normalize_repo_id(value: str | None) -> str | None:
    """Normalize repository identifier to canonical lower-case owner/repo."""
    if value is None:
        return None
    normalized = value.strip()
    if normalized.endswith(".git"):
        normalized = normalized[: -len(".git")]
    lowered = normalized.lower()
    if lowered.startswith("https://github.com/"):
        normalized = normalized[len("https://github.com/") :]
    elif lowered.startswith("http://github.com/"):
        normalized = normalized[len("http://github.com/") :]
    elif lowered.startswith("git@github.com:"):
        normalized = normalized[len("git@github.com:") :]
    normalized = normalized.strip("/")
    cleaned = normalized.lower()
    if cleaned and re.fullmatch(r"[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*", cleaned):
        return cleaned
    return None


def _normalize_number_token(value: Any) -> str | None:
    """Normalize issue/PR number fields into numeric string tokens."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.isdigit():
            return stripped
    return None


def _coerce_text(value: Any) -> str | None:
    """Coerce value into non-empty string token when possible."""
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, (int, float)):
        normalized = str(value).strip()
        return normalized or None
    return None


def _extract_event_timestamp(record: dict[str, Any]) -> datetime | None:
    """Extract one normalized UTC timestamp from rolling source record fields."""
    for key in _TIMESTAMP_KEYS:
        try:
            parsed = _parse_optional_timestamp(record.get(key))
        except ValueError:
            parsed = None
        if parsed is not None:
            return parsed
    return None


def _parse_optional_timestamp(value: Any) -> datetime | None:
    """Parse optional timestamp scalar to timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        candidate = stripped.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(candidate)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raise ValueError("timestamp must be ISO string, datetime, or unix epoch")


def _normalize_timestamp_string(value: str | None) -> str | None:
    """Normalize optional ISO timestamp strings for manifest metadata."""
    parsed = _parse_optional_timestamp(value)
    if parsed is None:
        return None
    return parsed.isoformat()


def _is_candidate_newer(
    *,
    current_ts: datetime | None,
    current_index: int,
    existing_ts: datetime | None,
    existing_index: int,
) -> bool:
    """Return true when current record should replace existing dedupe winner."""
    if current_ts is None and existing_ts is None:
        return current_index > existing_index
    if current_ts is None:
        return current_index > existing_index and existing_ts is None
    if existing_ts is None:
        return True
    if current_ts > existing_ts:
        return True
    if current_ts == existing_ts:
        return current_index > existing_index
    return False
