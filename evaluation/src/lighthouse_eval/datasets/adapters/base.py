from __future__ import annotations

import json
import os
from typing import Any, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field
from lighthouse_eval.context.base import ContextProvider
from lighthouse_eval.datasets.schema import Dataset
from lighthouse_eval.execution.evaluators.base import Evaluator


class RepoInfo(BaseModel):
    github_repo_id: int
    repo_url: str
    full_name: str
    branches: list[str] = Field(default_factory=lambda: ["main"])


def resolve_github_repo_id(
    full_name: str,
    *,
    github_token: str | None = None,
) -> int:
    """Resolve a GitHub repo full name (owner/name) to integer repo ID."""
    token = github_token or os.getenv("GITHUB_TOKEN")
    request = Request(
        f"https://api.github.com/repos/{full_name}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}" if token else "",
            "User-Agent": "lighthouse-eval/index-dataset",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Failed to resolve GitHub repo id for {full_name!r}") from exc

    repo_id = payload.get("id")
    if not isinstance(repo_id, int):
        raise RuntimeError(f"GitHub API did not return numeric id for {full_name!r}")
    return repo_id


@runtime_checkable
class DatasetAdapter(Protocol):
    """Loads an external or custom dataset into the canonical Task schema."""

    name: str
    transform_version: str

    def load(self, config: dict[str, Any]) -> Dataset: ...

    def get_evaluator(self) -> Evaluator: ...

    def get_oracle_provider(self) -> ContextProvider | None: ...

    def get_repos(self, config: dict[str, Any]) -> list[RepoInfo]: ...
