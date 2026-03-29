from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
from shared.schemas.search import WikiSearchRequest, WikiSearchResult
from shared.schemas.wiki import (
    GenerateWikiAcceptedResponse,
    GenerateWikiRequest,
    WikiStatusResponse,
)

from eval.lighthouse import (
    DEFAULT_INTERNAL_SERVICE_TOKEN_ENV_VAR,
    DEFAULT_LIGHTHOUSE_BRANCH,
    DEFAULT_SEARCH_SERVICE_URL,
    RepoRegistryEntry,
    resolve_repo_registry,
)
from eval.prompts import build_wiki_lighthouse_user_message
from eval.slice import SWEBenchTask

DEFAULT_WIKI_INGESTION_URL = "http://localhost:8001"
DEFAULT_WIKI_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_WIKI_TIMEOUT_SECONDS = 1_800.0
DEFAULT_WIKI_PROGRESS_HEARTBEAT_SECONDS = 30.0
DEFAULT_WIKI_TOP_K = 5
ACTIVE_WIKI_STATUSES = {"generating", "pending", "in_progress"}
TERMINAL_WIKI_STATUSES = {"completed", "failed"}


def prepare_lighthouse_wiki(
    *,
    tasks: list[SWEBenchTask],
    ingestion_url: str = DEFAULT_WIKI_INGESTION_URL,
    repo_registry_path: Path | None = None,
    github_repo_id: int | None = None,
    branch: str = DEFAULT_LIGHTHOUSE_BRANCH,
    poll_interval_seconds: float = DEFAULT_WIKI_POLL_INTERVAL_SECONDS,
    progress_heartbeat_seconds: float = DEFAULT_WIKI_PROGRESS_HEARTBEAT_SECONDS,
    timeout_seconds: float = DEFAULT_WIKI_TIMEOUT_SECONDS,
) -> None:
    if not tasks:
        raise ValueError("No SWE-bench tasks selected for wiki preparation.")
    if not ingestion_url.strip():
        raise ValueError("ingestion_url must not be empty.")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be greater than 0.")
    if progress_heartbeat_seconds <= 0:
        raise ValueError("progress_heartbeat_seconds must be greater than 0.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than 0.")

    repo_entries = resolve_repo_registry(
        tasks=tasks,
        repo_registry_path=repo_registry_path,
        github_repo_id=github_repo_id,
        branch=branch,
    )
    normalized_ingestion_url = ingestion_url.rstrip("/")
    unique_repos = sorted({task.repo.lower() for task in tasks})

    with httpx.Client(
        timeout=30.0,
        headers=_build_internal_service_headers(),
    ) as client:
        already_completed: dict[str, RepoRegistryEntry] = {}
        already_generating: dict[str, RepoRegistryEntry] = {}
        to_generate: dict[str, RepoRegistryEntry] = {}

        for repo_name in unique_repos:
            repo_entry = repo_entries[repo_name]
            status = get_wiki_status(
                client=client,
                ingestion_url=normalized_ingestion_url,
                github_repo_id=repo_entry.github_repo_id,
                branch=repo_entry.branch,
            )
            normalized_status = normalize_wiki_status(status.status if status else None)

            if normalized_status == "completed":
                print(f"Wiki already generated: {repo_name}@{repo_entry.branch}")
                already_completed[repo_name] = repo_entry
            elif normalized_status in ACTIVE_WIKI_STATUSES:
                print(f"Wiki already generating: {repo_name}@{repo_entry.branch}")
                already_generating[repo_name] = repo_entry
            else:
                to_generate[repo_name] = repo_entry

        if to_generate:
            print(f"Submitting {len(to_generate)} wiki generation request(s)")
            workflow_ids: list[str] = []
            for repo_name, repo_entry in to_generate.items():
                request = GenerateWikiRequest(
                    github_repo_id=repo_entry.github_repo_id,
                    branch=repo_entry.branch,
                )
                response = client.post(
                    f"{normalized_ingestion_url}/generate-wiki",
                    json=request.model_dump(mode="json"),
                )
                response.raise_for_status()
                accepted = GenerateWikiAcceptedResponse.model_validate(response.json())
                workflow_ids.append(accepted.workflow_id)
                print(
                    "Started wiki generation for "
                    f"{repo_name}@{repo_entry.branch} ({accepted.workflow_id})"
                )
            print(f"Accepted workflows: {', '.join(workflow_ids)}")
        elif already_generating:
            print("Selected repositories already have wiki generation in progress.")
        else:
            print("All selected repositories already have completed wiki generations.")

        repos_to_wait_for = {**already_generating, **to_generate}
        if repos_to_wait_for:
            wait_for_wiki_generation(
                client=client,
                ingestion_url=normalized_ingestion_url,
                repos=repos_to_wait_for,
                poll_interval_seconds=poll_interval_seconds,
                progress_heartbeat_seconds=progress_heartbeat_seconds,
                timeout_seconds=timeout_seconds,
            )


def build_wiki_lighthouse_messages(
    *,
    tasks: list[SWEBenchTask],
    search_service_url: str = DEFAULT_SEARCH_SERVICE_URL,
    top_k: int = DEFAULT_WIKI_TOP_K,
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
    with httpx.Client(
        timeout=30.0,
        headers=_build_internal_service_headers(),
    ) as client:
        for index, task in enumerate(tasks, start=1):
            repo_entry = repo_entries[task.repo.lower()]
            print(f"[{index}/{len(tasks)}] Retrieving wiki context for {task.instance_id}")
            print(
                "    repo target: "
                f"{task.repo} (github_repo_id={repo_entry.github_repo_id}, branch={repo_entry.branch})"
            )
            result = search_lighthouse_wiki(
                client=client,
                search_service_url=normalized_search_url,
                task=task,
                repo_entry=repo_entry,
                top_k=top_k,
            )
            print(f"    retrieved {len(result.snippets)} wiki snippet(s)")
            messages[task.instance_id] = build_wiki_lighthouse_user_message(task, result.snippets)
    return messages


def search_lighthouse_wiki(
    *,
    client: httpx.Client,
    search_service_url: str,
    task: SWEBenchTask,
    repo_entry: RepoRegistryEntry,
    top_k: int,
) -> WikiSearchResult:
    request = WikiSearchRequest(
        query=task.problem_statement.strip(),
        github_repo_id=repo_entry.github_repo_id,
        branch=repo_entry.branch,
        top_k=top_k,
    )

    try:
        response = client.post(
            f"{search_service_url}/search/wiki",
            json=request.model_dump(mode="json", exclude_none=True),
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            "Lighthouse wiki search returned "
            f"{exc.response.status_code} for {task.repo}: {exc.response.text}"
        ) from exc
    except httpx.RequestError as exc:
        raise RuntimeError(
            "Could not reach the Lighthouse search service at "
            f"{search_service_url}: {exc}"
        ) from exc

    return WikiSearchResult.model_validate(response.json())


def get_wiki_status(
    *,
    client: httpx.Client,
    ingestion_url: str,
    github_repo_id: int,
    branch: str,
) -> WikiStatusResponse | None:
    try:
        response = client.get(
            f"{ingestion_url}/wiki-status/{github_repo_id}",
            params={"branch": branch},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            "Wiki status lookup returned "
            f"{exc.response.status_code} for repo {github_repo_id}/{branch}: "
            f"{exc.response.text}"
        ) from exc
    except httpx.RequestError as exc:
        raise RuntimeError(
            "Could not reach the Lighthouse ingestion service at "
            f"{ingestion_url}: {exc}"
        ) from exc

    return WikiStatusResponse.model_validate(response.json())


def wait_for_wiki_generation(
    *,
    client: httpx.Client,
    ingestion_url: str,
    repos: dict[str, RepoRegistryEntry],
    poll_interval_seconds: float,
    progress_heartbeat_seconds: float,
    timeout_seconds: float,
) -> None:
    pending = dict(repos)
    started_at = time.monotonic()
    last_heartbeat_at = started_at

    while pending:
        completed_this_round: list[str] = []

        for repo_name, repo_entry in pending.items():
            status = get_wiki_status(
                client=client,
                ingestion_url=ingestion_url,
                github_repo_id=repo_entry.github_repo_id,
                branch=repo_entry.branch,
            )
            normalized_status = normalize_wiki_status(status.status if status else None)

            if normalized_status == "completed":
                page_count = 0 if status is None else status.page_count
                print(
                    f"Wiki ready: {repo_name}@{repo_entry.branch} "
                    f"({page_count} page(s))"
                )
                completed_this_round.append(repo_name)
                continue

            if normalized_status == "failed":
                raise RuntimeError(f"Wiki generation failed for {repo_name}@{repo_entry.branch}")

        for repo_name in completed_this_round:
            pending.pop(repo_name, None)

        if not pending:
            return

        now = time.monotonic()
        elapsed_seconds = now - started_at
        if elapsed_seconds > timeout_seconds:
            pending_display = ", ".join(
                f"{repo_name}@{repo_entry.branch}" for repo_name, repo_entry in pending.items()
            )
            raise TimeoutError(
                "Timed out waiting for wiki generation to finish for: "
                f"{pending_display}"
            )

        if now - last_heartbeat_at >= progress_heartbeat_seconds:
            pending_display = ", ".join(
                f"{repo_name}@{repo_entry.branch}" for repo_name, repo_entry in pending.items()
            )
            print(
                f"Still waiting after {int(elapsed_seconds)}s for wiki generation: "
                f"{pending_display}"
            )
            last_heartbeat_at = now

        time.sleep(poll_interval_seconds)


def normalize_wiki_status(status: str | None) -> str | None:
    if status is None:
        return None
    normalized = status.strip().lower()
    return normalized or None


def _build_internal_service_headers() -> dict[str, str]:
    token = os.environ.get(DEFAULT_INTERNAL_SERVICE_TOKEN_ENV_VAR, "").strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}
