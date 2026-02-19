"""Version-pinned SWE-bench snapshot adapter for offline ingest."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

_SUPPORTED_SUFFIXES = {".json", ".jsonl"}
_JSON_RECORD_KEYS = ("instances", "records", "data")
_VERSION_RECORD_KEYS = (
    "dataset_version",
    "version",
    "benchmark_version",
    "snapshot_version",
)
_VERSIONED_FILE_PATTERNS = (
    "swebench-{version}.jsonl",
    "swebench_{version}.jsonl",
    "{version}.jsonl",
    "swebench-{version}.json",
    "swebench_{version}.json",
    "{version}.json",
)
_VERSION_DIR_DEFAULT_FILES = (
    "instances.jsonl",
    "dataset_instances.jsonl",
    "swebench.jsonl",
    "records.jsonl",
    "instances.json",
    "dataset_instances.json",
    "swebench.json",
    "records.json",
)


@dataclass(frozen=True, slots=True)
class SwebenchSnapshot:
    """Loaded immutable SWE-bench snapshot records and source metadata."""

    dataset_version: str
    source_path: str
    source_mode: str
    source_format: str
    snapshot_sha256: str
    snapshot_size_bytes: int
    records: list[dict[str, Any]]


class SwebenchSnapshotAdapter:
    """Load version-pinned SWE-bench snapshots from local JSON/JSONL files."""

    def load_snapshot(
        self,
        *,
        dataset_version: str,
        dataset_source_path: str,
    ) -> SwebenchSnapshot:
        """Load one immutable snapshot file tied to an explicit version label."""
        version = self._validate_version(dataset_version)
        requested_path = self._resolve_input_path(dataset_source_path)
        source_mode = "directory_path" if requested_path.is_dir() else "file_path"
        source_path = self._resolve_source_file(
            requested_path=requested_path,
            dataset_version=version,
        )
        source_format = source_path.suffix.lower().lstrip(".")

        snapshot_bytes = source_path.read_bytes()
        snapshot_sha256 = hashlib.sha256(snapshot_bytes).hexdigest()
        records = self._parse_records(source_path=source_path)
        self._validate_record_versions(records=records, dataset_version=version)

        return SwebenchSnapshot(
            dataset_version=version,
            source_path=str(source_path),
            source_mode=source_mode,
            source_format=source_format,
            snapshot_sha256=snapshot_sha256,
            snapshot_size_bytes=len(snapshot_bytes),
            records=records,
        )

    def _validate_version(self, dataset_version: str) -> str:
        """Validate explicit dataset version pin for immutable snapshot loading."""
        version = dataset_version.strip()
        if not version:
            raise ValueError("dataset_version is required for SWE-bench snapshots")
        return version

    def _resolve_input_path(self, dataset_source_path: str) -> Path:
        """Resolve and validate provided source path exists on local disk."""
        source_path = dataset_source_path.strip()
        if not source_path:
            raise ValueError("dataset_source_path is required for SWE-bench snapshots")
        path = Path(source_path).expanduser()
        if not path.exists():
            raise ValueError(f"dataset_source_path does not exist: {path}")
        return path.resolve()

    def _resolve_source_file(
        self,
        *,
        requested_path: Path,
        dataset_version: str,
    ) -> Path:
        """Resolve one concrete versioned JSON/JSONL snapshot file."""
        if requested_path.is_file():
            self._validate_file_extension(requested_path)
            if not self._path_contains_version_hint(requested_path, dataset_version):
                raise ValueError(
                    "SWE-bench snapshot path must encode dataset_version in the path "
                    f"(dataset_version={dataset_version}, source={requested_path})"
                )
            return requested_path

        if not requested_path.is_dir():
            raise ValueError(
                "dataset_source_path must be a file or directory "
                f"(received: {requested_path})"
            )

        candidate = self._resolve_versioned_file_from_directory(
            source_dir=requested_path,
            dataset_version=dataset_version,
        )
        if candidate is None:
            raise ValueError(
                "Could not resolve a version-pinned SWE-bench snapshot in directory "
                f"{requested_path} for dataset_version={dataset_version}"
            )
        return candidate

    def _resolve_versioned_file_from_directory(
        self,
        *,
        source_dir: Path,
        dataset_version: str,
    ) -> Path | None:
        """Find one version-matching snapshot file inside a directory."""
        for candidate_name in self._candidate_versioned_filenames(dataset_version):
            candidate = source_dir / candidate_name
            if candidate.is_file():
                return candidate.resolve()

        if self._path_contains_version_hint(source_dir, dataset_version):
            for fallback_name in _VERSION_DIR_DEFAULT_FILES:
                candidate = source_dir / fallback_name
                if candidate.is_file():
                    return candidate.resolve()

        for child in source_dir.iterdir():
            if not child.is_dir():
                continue
            if not self._path_contains_version_hint(child, dataset_version):
                continue
            for fallback_name in _VERSION_DIR_DEFAULT_FILES:
                candidate = child / fallback_name
                if candidate.is_file():
                    return candidate.resolve()

        return None

    def _candidate_versioned_filenames(self, dataset_version: str) -> tuple[str, ...]:
        """Generate likely versioned file names for SWE-bench snapshots."""
        variants = {
            dataset_version,
            dataset_version.lower(),
            self._sanitize_version_for_filename(dataset_version),
            self._sanitize_version_for_filename(dataset_version).lower(),
        }
        candidates: list[str] = []
        for variant in variants:
            if not variant:
                continue
            for pattern in _VERSIONED_FILE_PATTERNS:
                candidates.append(pattern.format(version=variant))
        return tuple(dict.fromkeys(candidates))

    def _sanitize_version_for_filename(self, dataset_version: str) -> str:
        """Sanitize one dataset version for filename candidate generation."""
        return re.sub(r"[^A-Za-z0-9._-]+", "_", dataset_version.strip())

    def _path_contains_version_hint(self, path: Path, dataset_version: str) -> bool:
        """Check whether a path encodes the required version token."""
        version_token = self._normalize_token(dataset_version)
        if not version_token:
            return False
        for part in path.parts:
            part_token = self._normalize_token(part)
            if not part_token:
                continue
            if version_token in part_token:
                return True
        return False

    def _normalize_token(self, value: str) -> str:
        """Normalize free-form strings for lenient version-token comparisons."""
        return re.sub(r"[^A-Za-z0-9]+", "", value.strip().lower())

    def _validate_file_extension(self, path: Path) -> None:
        """Ensure snapshot source file extension is supported."""
        suffix = path.suffix.lower()
        if suffix not in _SUPPORTED_SUFFIXES:
            raise ValueError(
                "SWE-bench snapshot file must be .json or .jsonl "
                f"(received: {path})"
            )

    def _parse_records(self, *, source_path: Path) -> list[dict[str, Any]]:
        """Parse records from one JSON/JSONL snapshot file."""
        suffix = source_path.suffix.lower()
        if suffix == ".jsonl":
            return self._parse_jsonl_records(source_path)
        if suffix == ".json":
            return self._parse_json_records(source_path)
        raise ValueError(
            "SWE-bench snapshot file must be .json or .jsonl "
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
                        f"SWE-bench JSONL record at line {line_index} must be an object"
                    )
                records.append(parsed)
        if not records:
            raise ValueError(f"SWE-bench snapshot is empty: {source_path}")
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
            "SWE-bench JSON source must be a list of records or object containing "
            f"one of keys: {', '.join(_JSON_RECORD_KEYS)}"
        )

    def _validate_record_list(
        self,
        records: list[Any],
        *,
        context: str,
    ) -> list[dict[str, Any]]:
        """Validate parsed record lists contain only object rows."""
        if not records:
            raise ValueError(f"SWE-bench snapshot {context} cannot be empty")
        validated: list[dict[str, Any]] = []
        for index, row in enumerate(records):
            if not isinstance(row, dict):
                raise ValueError(
                    f"SWE-bench snapshot {context}[{index}] must be an object"
                )
            validated.append(row)
        return validated

    def _validate_record_versions(
        self,
        *,
        records: list[dict[str, Any]],
        dataset_version: str,
    ) -> None:
        """Ensure embedded record-version hints do not conflict with pinned version."""
        expected = self._normalize_token(dataset_version)
        if not expected:
            return
        for index, record in enumerate(records):
            for key in _VERSION_RECORD_KEYS:
                value = record.get(key)
                if not isinstance(value, str):
                    continue
                normalized = self._normalize_token(value)
                if not normalized:
                    continue
                if normalized != expected:
                    raise ValueError(
                        "SWE-bench snapshot contains record with mismatched "
                        f"{key} at index {index}: expected {dataset_version}, "
                        f"received {value}"
                    )
