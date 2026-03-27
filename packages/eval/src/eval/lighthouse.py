from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import httpx
from shared.schemas.search import CodeSnippet, HybridRequest, SearchResult

from eval.prompts import build_lighthouse_user_message
from eval.slice import SWEBenchTask

DEFAULT_SEARCH_SERVICE_URL = "http://localhost:8002"
DEFAULT_SEARCH_TOP_K = 8
DEFAULT_LIGHTHOUSE_BRANCH = "main"


@dataclass(frozen=True)
class RepoRegistryEntry:
    github_repo_id: int
    branch: str


def build_lighthouse_messages(
    *,
    tasks: list[SWEBenchTask],
    search_service_url: str = DEFAULT_SEARCH_SERVICE_URL,
    top_k: int = DEFAULT_SEARCH_TOP_K,
    repo_registry_path: Path | None = None,
    github_repo_id: int | None = None,
    branch: str = DEFAULT_LIGHTHOUSE_BRANCH,
) -> dict[str, str]:
    if not tasks:
        raise ValueError("No SWE-bench tasks selected for Lighthouse generation.")
    if top_k < 1:
        raise ValueError("top_k must be at least 1.")
    if not search_service_url.strip():
        raise ValueError("search_service_url must not be empty.")

    repo_entries = resolve_repo_registry(
        tasks=tasks,
        repo_registry_path=repo_registry_path,
        github_repo_id=github_repo_id,
        branch=branch,
    )

    messages: dict[str, str] = {}
    normalized_search_url = search_service_url.rstrip("/")
    with httpx.Client(timeout=30.0) as client:
        for index, task in enumerate(tasks, start=1):
            repo_entry = repo_entries[task.repo.lower()]
            print(f"[{index}/{len(tasks)}] Retrieving Lighthouse context for {task.instance_id}")
            print(
                "    repo target: "
                f"{task.repo} (github_repo_id={repo_entry.github_repo_id}, branch={repo_entry.branch})"
            )
            result = search_lighthouse(
                client=client,
                search_service_url=normalized_search_url,
                task=task,
                repo_entry=repo_entry,
                top_k=top_k,
            )
            print(f"    retrieved {len(result.snippets)} snippet(s)")
            messages[task.instance_id] = build_lighthouse_user_message(task, result.snippets)
    return messages


def resolve_repo_registry(
    *,
    tasks: list[SWEBenchTask],
    repo_registry_path: Path | None,
    github_repo_id: int | None,
    branch: str,
) -> dict[str, RepoRegistryEntry]:
    if github_repo_id is not None:
        repos = {task.repo.lower() for task in tasks}
        if len(repos) != 1:
            repo_list = ", ".join(sorted(repos))
            raise ValueError(
                "--github-repo-id can only be used when all selected tasks belong to "
                f"one repository. Selected repositories: {repo_list}"
            )
        repo_name = next(iter(repos))
        return {
            repo_name: RepoRegistryEntry(
                github_repo_id=github_repo_id,
                branch=branch.strip() or DEFAULT_LIGHTHOUSE_BRANCH,
            )
        }

    if repo_registry_path is None:
        raise ValueError(
            "Provide either --repo-registry or --github-repo-id for Lighthouse generation."
        )

    raw_entries = load_repo_registry(repo_registry_path)
    missing = sorted({task.repo.lower() for task in tasks if task.repo.lower() not in raw_entries})
    if missing:
        missing_display = ", ".join(missing)
        raise ValueError(
            "Repository registry is missing entries for the selected SWE-bench repositories: "
            f"{missing_display}"
        )
    return raw_entries


def load_repo_registry(path: Path) -> dict[str, RepoRegistryEntry]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Repository registry not found: {path}")

    raw_data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw_data, dict) and "repositories" in raw_data:
        raw_data = raw_data["repositories"]
    if not isinstance(raw_data, Mapping):
        raise ValueError("Repository registry must be a JSON object or contain a 'repositories' object.")

    entries: dict[str, RepoRegistryEntry] = {}
    for repo_name, value in raw_data.items():
        if not isinstance(repo_name, str):
            continue
        typed_entry = _as_mapping(value)
        if typed_entry is None:
            continue
        github_repo_id = typed_entry.get("github_repo_id")
        if not isinstance(github_repo_id, int) or github_repo_id < 1:
            raise ValueError(
                f"Registry entry for {repo_name!r} is missing a valid github_repo_id."
            )
        branch = str(typed_entry.get("branch", DEFAULT_LIGHTHOUSE_BRANCH)).strip()
        if not branch:
            branch = DEFAULT_LIGHTHOUSE_BRANCH
        entries[repo_name.strip().lower()] = RepoRegistryEntry(
            github_repo_id=github_repo_id,
            branch=branch,
        )

    if not entries:
        raise ValueError(f"Repository registry {path} does not contain any valid entries.")
    return entries


def search_lighthouse(
    *,
    client: httpx.Client,
    search_service_url: str,
    task: SWEBenchTask,
    repo_entry: RepoRegistryEntry,
    top_k: int,
) -> SearchResult:
    request = HybridRequest(
        query=task.problem_statement.strip(),
        github_repo_id=repo_entry.github_repo_id,
        branch=repo_entry.branch,
        top_k=top_k,
    )

    try:
        response = client.post(
            f"{search_service_url}/search",
            json=[request.model_dump(mode="json")],
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            "Lighthouse search returned "
            f"{exc.response.status_code} for {task.repo}: {exc.response.text}"
        ) from exc
    except httpx.RequestError as exc:
        raise RuntimeError(
            "Could not reach the Lighthouse search service at "
            f"{search_service_url}: {exc}"
        ) from exc

    return SearchResult.model_validate(response.json())


def summarize_snippets(snippets: list[CodeSnippet]) -> str:
    if not snippets:
        return "no snippets"
    return ", ".join(
        f"{snippet.file_path}:{snippet.start_line}-{snippet.end_line}" for snippet in snippets
    )


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return None
