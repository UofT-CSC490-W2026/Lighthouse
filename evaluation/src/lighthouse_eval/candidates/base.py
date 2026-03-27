from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal, cast

from pydantic import BaseModel, Discriminator, Field, Tag

from lighthouse_eval.datasets.schema import OutputFormat


def _resolve_workspace_path(workspace: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute():
        raise ValueError(f"Candidate path must be relative to the workspace: {relative_path!r}")

    workspace_root = workspace.resolve()
    target = (workspace / path).resolve(strict=False)
    try:
        target.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(f"Candidate path escapes the workspace: {relative_path!r}") from exc
    return target


_PATCH_HEADER_RE = re.compile(
    r"^(?P<prefix>diff --git|---|\+\+\+|rename from|rename to|copy from|copy to)\s+(?P<rest>.*)$"
)


def _normalise_patch_path(raw_path: str) -> str | None:
    path = raw_path.strip().split("\t", 1)[0]
    if path == "/dev/null":
        return None
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path


def _validate_patch_paths(diff: str, workspace: Path) -> None:
    for line in diff.splitlines():
        match = _PATCH_HEADER_RE.match(line)
        if not match:
            continue

        prefix = match.group("prefix")
        rest = match.group("rest")

        raw_paths: list[str]
        if prefix == "diff --git":
            parts = rest.split(maxsplit=1)
            raw_paths = parts if len(parts) == 2 else []
        else:
            raw_paths = [rest]

        for raw_path in raw_paths:
            path = _normalise_patch_path(raw_path)
            if path is not None:
                _resolve_workspace_path(workspace, path)


class _CandidateBase(BaseModel):
    """Internal base — never instantiate directly."""

    def apply(self, workspace: Path) -> None:
        raise NotImplementedError


class FileRewrite(_CandidateBase):
    """Replace (or create) a single file with new content."""

    kind: Literal[OutputFormat.file] = OutputFormat.file
    filename: str
    content: str

    def apply(self, workspace: Path) -> None:
        target = _resolve_workspace_path(workspace, self.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.content, encoding="utf-8")


class MultiFileRewrite(_CandidateBase):
    """Replace (or create) multiple files."""

    kind: Literal[OutputFormat.multi_file] = OutputFormat.multi_file
    files: dict[str, str] = Field(description="{relative_path: content}")

    def apply(self, workspace: Path) -> None:
        for rel_path, content in self.files.items():
            target = _resolve_workspace_path(workspace, rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")


class UnifiedPatch(_CandidateBase):
    """Apply a unified diff to the workspace."""

    kind: Literal[OutputFormat.patch] = OutputFormat.patch
    diff: str

    def apply(self, workspace: Path) -> None:
        import subprocess

        _validate_patch_paths(self.diff, workspace)
        result = subprocess.run(
            ["patch", "-p1", "--no-backup-if-mismatch"],
            input=self.diff,
            capture_output=True,
            text=True,
            cwd=workspace,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to apply patch.\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )


class Completion(_CandidateBase):
    """A short code completion (1-N lines)."""

    kind: Literal[OutputFormat.completion] = OutputFormat.completion
    text: str
    target_file: str | None = Field(
        default=None,
        description="If set, append the completion to this file in the workspace.",
    )

    def apply(self, workspace: Path) -> None:
        if self.target_file is None:
            return
        target = _resolve_workspace_path(workspace, self.target_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        target.write_text(existing + self.text, encoding="utf-8")


def _candidate_discriminator(v: object) -> str:
    if isinstance(v, dict):
        raw = cast(dict[str, object], v)
        kind = raw.get("kind")
        if isinstance(kind, OutputFormat):
            return kind.value
        if isinstance(kind, str):
            return kind
        return OutputFormat.file.value

    kind = getattr(v, "kind", OutputFormat.file)
    if isinstance(kind, OutputFormat):
        return kind.value
    if isinstance(kind, str):
        return kind
    return OutputFormat.file.value


CandidateEdit = Annotated[
    Annotated[FileRewrite, Tag(OutputFormat.file)]
    | Annotated[MultiFileRewrite, Tag(OutputFormat.multi_file)]
    | Annotated[UnifiedPatch, Tag(OutputFormat.patch)]
    | Annotated[Completion, Tag(OutputFormat.completion)],
    Discriminator(_candidate_discriminator),
]
"""Discriminated union over all candidate-edit types.

Use as a type annotation; Pydantic will deserialise to the correct subclass
based on the ``kind`` field.
"""
