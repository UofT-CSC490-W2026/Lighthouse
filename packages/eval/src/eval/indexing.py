from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from shared.schemas.ingestion import (
    IndexAcceptedResponse,
    IndexRequest,
    IndexStatusResponse,
    RepoIndexRequest,
)

from eval.lighthouse import RepoRegistryEntry
from eval.slice import SWEBenchTask

DEFAULT_INGESTION_URL = "http://localhost:8001"
DEFAULT_REPO_REGISTRY_OUTPUT = Path(".cache/eval/repo-registry.json")
DEFAULT_STATUS_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_STATUS_TIMEOUT_SECONDS = 1_800.0


@dataclass(frozen=True)
class ResolvedRepository:
    full_name: str
    github_repo_id: int
    repo_url: str
    branch: str


def index_swebench_repositories(
    *,
    tasks: list[SWEBenchTask],
    ingestion_url: str = DEFAULT_INGESTION_URL,
    output_path: Path = DEFAULT_REPO_REGISTRY_OUTPUT,
    github_token: str | None = None,
    poll_interval_seconds: float = DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
    timeout_seconds: float = DEFAULT_STATUS_TIMEOUT_SECONDS,
) -> Path:
    if not tasks:
        raise ValueError("No SWE-bench tasks selected for repository indexing.")
    if not ingestion_url.strip():
        raise ValueError("ingestion_url must not be empty.")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be greater than 0.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than 0.")

    token = github_token or os.environ.get("GITHUB_TOKEN")
    resolved_repos = resolve_repositories(tasks=tasks, github_token=token)
    normalized_ingestion_url = ingestion_url.rstrip("/")

    with httpx.Client(timeout=30.0) as client:
        already_indexed: dict[str, ResolvedRepository] = {}
        to_index: list[ResolvedRepository] = []

        for repo in resolved_repos:
            status = get_index_status(
                client=client,
                ingestion_url=normalized_ingestion_url,
                github_repo_id=repo.github_repo_id,
            )
            branch_status = branch_status_for(status, repo.branch) if status is not None else None
            if branch_status == "indexed":
                print(f"Already indexed: {repo.full_name}@{repo.branch}")
                already_indexed[repo.full_name] = repo
            else:
                to_index.append(repo)

        if to_index:
            print(f"Submitting {len(to_index)} repository indexing request(s)")
            request = IndexRequest(
                repositories=[
                    RepoIndexRequest(
                        github_repo_id=repo.github_repo_id,
                        repo_url=repo.repo_url,
                        full_name=repo.full_name,
                        branches=[repo.branch],
                        github_token=token,
                    )
                    for repo in to_index
                ]
            )
            response = client.post(
                f"{normalized_ingestion_url}/index",
                json=request.model_dump(mode="json"),
            )
            response.raise_for_status()
            accepted = IndexAcceptedResponse.model_validate(response.json())
            print(f"Accepted workflows: {', '.join(accepted.workflow_ids)}")
            wait_for_indexing(
                client=client,
                ingestion_url=normalized_ingestion_url,
                repos=to_index,
                poll_interval_seconds=poll_interval_seconds,
                timeout_seconds=timeout_seconds,
            )
        else:
            print("All selected repositories are already indexed for the requested branches.")

    registry = {
        repo.full_name: RepoRegistryEntry(
            github_repo_id=repo.github_repo_id,
            branch=repo.branch,
        )
        for repo in resolved_repos
    }
    write_repo_registry(output_path=output_path, registry=registry)
    return output_path.resolve()


def resolve_repositories(
    *,
    tasks: list[SWEBenchTask],
    github_token: str | None,
) -> list[ResolvedRepository]:
    repo_names = sorted({task.repo.strip().lower() for task in tasks if task.repo.strip()})
    if not repo_names:
        raise ValueError("No repository names were found in the selected SWE-bench tasks.")

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    resolved: list[ResolvedRepository] = []
    with httpx.Client(headers=headers, timeout=30.0) as client:
        for repo_name in repo_names:
            print(f"Resolving GitHub metadata for {repo_name}")
            response = client.get(f"https://api.github.com/repos/{repo_name}")
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    "Failed to resolve GitHub metadata for "
                    f"{repo_name}: {exc.response.status_code} {exc.response.text}"
                ) from exc

            data = response.json()
            github_repo_id = data.get("id")
            repo_url = data.get("html_url")
            default_branch = data.get("default_branch")

            if not isinstance(github_repo_id, int) or github_repo_id < 1:
                raise RuntimeError(f"GitHub metadata for {repo_name} is missing a valid repo id.")
            if not isinstance(repo_url, str) or not repo_url.strip():
                raise RuntimeError(f"GitHub metadata for {repo_name} is missing html_url.")
            if not isinstance(default_branch, str) or not default_branch.strip():
                raise RuntimeError(
                    f"GitHub metadata for {repo_name} is missing default_branch."
                )

            resolved.append(
                ResolvedRepository(
                    full_name=repo_name,
                    github_repo_id=github_repo_id,
                    repo_url=repo_url.strip(),
                    branch=default_branch.strip(),
                )
            )
            print(
                "    resolved -> "
                f"github_repo_id={github_repo_id}, branch={default_branch.strip()}"
            )

    return resolved


def get_index_status(
    *,
    client: httpx.Client,
    ingestion_url: str,
    github_repo_id: int,
) -> IndexStatusResponse | None:
    response = client.get(f"{ingestion_url}/status/{github_repo_id}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return IndexStatusResponse.model_validate(response.json())


def branch_status_for(status: IndexStatusResponse, branch_name: str) -> str | None:
    for branch in status.branches:
        if branch.branch_name == branch_name:
            return branch.status
    return None


def wait_for_indexing(
    *,
    client: httpx.Client,
    ingestion_url: str,
    repos: list[ResolvedRepository],
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    pending = {repo.full_name: repo for repo in repos}
    last_seen_status: dict[str, str] = {}

    while pending:
        if time.monotonic() > deadline:
            pending_display = ", ".join(
                f"{repo.full_name}@{repo.branch}" for repo in pending.values()
            )
            raise TimeoutError(
                "Timed out while waiting for repository indexing to finish: "
                f"{pending_display}"
            )

        for full_name, repo in list(pending.items()):
            status = get_index_status(
                client=client,
                ingestion_url=ingestion_url,
                github_repo_id=repo.github_repo_id,
            )
            branch_status = branch_status_for(status, repo.branch) if status is not None else None
            normalized_status = branch_status or "pending"

            if last_seen_status.get(full_name) != normalized_status:
                print(f"Index status: {repo.full_name}@{repo.branch} -> {normalized_status}")
                last_seen_status[full_name] = normalized_status

            if normalized_status == "indexed":
                pending.pop(full_name)
                continue

            if normalized_status in {"failed", "error"}:
                raise RuntimeError(
                    f"Repository indexing failed for {repo.full_name}@{repo.branch}"
                )

        if pending:
            time.sleep(poll_interval_seconds)


def write_repo_registry(
    *,
    output_path: Path,
    registry: dict[str, RepoRegistryEntry],
) -> None:
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        repo_name: {
            "github_repo_id": entry.github_repo_id,
            "branch": entry.branch,
        }
        for repo_name, entry in sorted(registry.items())
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
