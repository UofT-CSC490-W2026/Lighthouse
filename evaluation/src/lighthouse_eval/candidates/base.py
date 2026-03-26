from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, Field, Tag

from lighthouse_eval.datasets.schema import OutputFormat


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
        target = workspace / self.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.content, encoding="utf-8")


class MultiFileRewrite(_CandidateBase):
    """Replace (or create) multiple files."""

    kind: Literal[OutputFormat.multi_file] = OutputFormat.multi_file
    files: dict[str, str] = Field(description="{relative_path: content}")

    def apply(self, workspace: Path) -> None:
        for rel_path, content in self.files.items():
            target = workspace / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")


class UnifiedPatch(_CandidateBase):
    """Apply a unified diff to the workspace."""

    kind: Literal[OutputFormat.patch] = OutputFormat.patch
    diff: str

    def apply(self, workspace: Path) -> None:
        import subprocess

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
        target = workspace / self.target_file
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        target.write_text(existing + self.text, encoding="utf-8")


def _candidate_discriminator(v: object) -> str:
    if isinstance(v, dict):
        return v.get("kind", OutputFormat.file)  # type: ignore[return-value]
    return getattr(v, "kind", OutputFormat.file)


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
