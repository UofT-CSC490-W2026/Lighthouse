"""Dependency-context retrieval service for MCP tool calls."""

from __future__ import annotations

import re

from ..types import (
    DependencyContextRecord,
    DependencySourceType,
    GetDependencyContextRequest,
    GetDependencyContextResponse,
)
from .retrieval_backend import RetrievalBackendService


class DependencyService:
    """Provide dependency context using runtime-indexed repository artifacts."""

    def __init__(
        self,
        *,
        retrieval_backend: RetrievalBackendService,
    ) -> None:
        self.retrieval_backend = retrieval_backend

    async def get_dependency_context(
        self, request: GetDependencyContextRequest
    ) -> GetDependencyContextResponse:
        """Return dependency context records resolved from runtime chunk search."""
        query_text = self._build_query_text(request)
        hits = await self.retrieval_backend.search(
            repo_id=request.repo_id,
            ref=request.ref,
            query_text=query_text,
            top_k=8,
            path_hint=None,
        )
        if not hits:
            return GetDependencyContextResponse()

        docs: list[DependencyContextRecord] = []
        installed_version: str | None = None
        changelog_notes: list[str] = []
        known_issues: list[str] = []
        for hit in hits:
            if installed_version is None:
                installed_version = _extract_version(
                    package=request.package,
                    text=hit.text,
                )

            if "changelog" in hit.path.lower():
                changelog_notes.append(_truncate_line(hit.text))
            if "fixme" in hit.text.lower() or "todo" in hit.text.lower():
                known_issues.append(
                    f"{hit.path}:{hit.start_char}-{hit.end_char} mentions open TODO/FIXME notes."
                )

            docs.append(
                DependencyContextRecord(
                    source_type=DependencySourceType.source_code,
                    location=f"{hit.path}:{hit.start_char}-{hit.end_char}",
                    content=hit.text,
                    relevance=(
                        f"Semantic match for dependency '{request.package}' "
                        f"in runtime-indexed chunk {hit.chunk_index}."
                    ),
                )
            )

        return GetDependencyContextResponse(
            installed_version=installed_version,
            relevant_docs=docs,
            changelog_notes=_dedupe_preserve_order(changelog_notes),
            known_issues=_dedupe_preserve_order(known_issues),
            version_sensitivity=(
                "Likely version-sensitive dependency path."
                if installed_version is not None
                else "Version marker not found in indexed context."
            ),
        )

    def _build_query_text(self, request: GetDependencyContextRequest) -> str:
        """Build semantic query text for dependency-context lookup."""
        parts = [request.package.strip()]
        if request.api:
            parts.append(request.api.strip())
        parts.append("dependency version import usage requirements lockfile")
        return "\n".join(part for part in parts if part)


def _extract_version(*, package: str, text: str) -> str | None:
    """Extract a dependency version string from one chunk of text, if present."""
    normalized_package = package.strip()
    if not normalized_package:
        return None

    python_pattern = re.compile(
        rf"(?im)^\s*{re.escape(normalized_package)}\s*(?:==|~=|>=|<=|>|<)\s*([A-Za-z0-9._+-]+)\s*$"
    )
    npm_pattern = re.compile(
        rf'(?i)"{re.escape(normalized_package)}"\s*:\s*"([^"]+)"'
    )
    poetry_pattern = re.compile(
        rf'(?i){re.escape(normalized_package)}\s*=\s*"([^"]+)"'
    )

    for pattern in (python_pattern, npm_pattern, poetry_pattern):
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def _truncate_line(text: str, *, max_len: int = 200) -> str:
    """Return the first non-empty line, truncated for compact response payloads."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) <= max_len:
            return stripped
        return f"{stripped[:max_len - 3]}..."
    return ""


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    """De-duplicate a list while preserving original item order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped
