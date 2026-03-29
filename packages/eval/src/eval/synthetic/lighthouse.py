from __future__ import annotations

import os
from pathlib import Path

import httpx
from shared.schemas.ingestion import IndexAcceptedResponse
from shared.schemas.search import (
    SearchRequest,
    SearchResult,
    WikiSearchRequest,
    WikiSearchResult,
)

from eval.indexing import (
    DEFAULT_INGESTION_URL,
    DEFAULT_PROGRESS_HEARTBEAT_SECONDS,
    DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
    DEFAULT_STATUS_TIMEOUT_SECONDS,
    ACTIVE_INDEX_STATUSES,
    IngestionWorkerLogStreamer,
    branch_status_for,
    find_compose_project_root,
    get_index_status,
    normalize_branch_status,
    resolve_stream_worker_logs_setting,
    wait_for_indexing,
)
from eval.lighthouse import DEFAULT_SEARCH_SERVICE_URL, DEFAULT_SEARCH_TOP_K
from eval.wiki import (
    DEFAULT_WIKI_POLL_INTERVAL_SECONDS,
    DEFAULT_WIKI_PROGRESS_HEARTBEAT_SECONDS,
    DEFAULT_WIKI_TIMEOUT_SECONDS,
    ACTIVE_WIKI_STATUSES,
    get_wiki_status,
    normalize_wiki_status,
    submit_wiki_generation_request,
    wait_for_wiki_generation,
)
from .prompts import (
    build_synthetic_code_lighthouse_user_message,
    build_synthetic_search_query,
    build_synthetic_wiki_lighthouse_user_message,
)
from .workspace import (
    PreparedSyntheticWorkspace,
    SyntheticTask,
    build_synthetic_index_request,
    build_synthetic_wiki_request,
    shared_repo_entry,
    shared_resolved_repository,
    synthetic_repo_url_for_container,
)

DEFAULT_SYNTHETIC_WIKI_INGESTION_URL = DEFAULT_INGESTION_URL
DEFAULT_SYNTHETIC_CONTEXT_SOURCE = "code"


def index_synthetic_repository(
    *,
    workspace: PreparedSyntheticWorkspace,
    ingestion_url: str = DEFAULT_INGESTION_URL,
    github_token: str | None = None,
    stream_worker_logs: bool | None = None,
    poll_interval_seconds: float = DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
    progress_heartbeat_seconds: float = DEFAULT_PROGRESS_HEARTBEAT_SECONDS,
    timeout_seconds: float = DEFAULT_STATUS_TIMEOUT_SECONDS,
) -> Path:
    if not ingestion_url.strip():
        raise ValueError("ingestion_url must not be empty.")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be greater than 0.")
    if progress_heartbeat_seconds <= 0:
        raise ValueError("progress_heartbeat_seconds must be greater than 0.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than 0.")

    repo = shared_resolved_repository(workspace)
    normalized_ingestion_url = ingestion_url.rstrip("/")
    compose_root = find_compose_project_root(Path.cwd())
    should_stream_logs = resolve_stream_worker_logs_setting(
        stream_worker_logs=stream_worker_logs,
        ingestion_url=normalized_ingestion_url,
        compose_root=compose_root,
    )

    with IngestionWorkerLogStreamer(
        compose_root=compose_root, enabled=should_stream_logs
    ):
        with httpx.Client(
            timeout=30.0, headers=_build_internal_service_headers()
        ) as client:
            status = get_index_status(
                client=client,
                ingestion_url=normalized_ingestion_url,
                github_repo_id=repo.github_repo_id,
            )
            branch_status = normalize_branch_status(
                branch_status_for(status, repo.branch) if status is not None else None
            )
            initial_statuses = {repo.full_name: branch_status}

            if branch_status == "indexed":
                print(f"Already indexed: {repo.full_name}@{repo.branch}")
                return workspace.repo_registry_path.resolve()

            if branch_status in ACTIVE_INDEX_STATUSES:
                print(f"Already indexing: {repo.full_name}@{repo.branch}")
                wait_for_indexing(
                    client=client,
                    ingestion_url=normalized_ingestion_url,
                    repos=[repo],
                    initial_statuses=initial_statuses,
                    allow_stale_terminal_statuses=set(),
                    poll_interval_seconds=poll_interval_seconds,
                    progress_heartbeat_seconds=progress_heartbeat_seconds,
                    timeout_seconds=timeout_seconds,
                )
                return workspace.repo_registry_path.resolve()

            print(
                f"Submitting synthetic indexing request for {repo.full_name}@{repo.branch}"
            )
            repo_url_override: str | None = None
            if compose_root is not None and _is_local_service_url(
                normalized_ingestion_url
            ):
                repo_url_override = synthetic_repo_url_for_container(
                    workspace,
                    compose_root=compose_root,
                )
                print(f"Using container-visible repo path: {repo_url_override}")
            request = build_synthetic_index_request(
                workspace,
                github_token=github_token,
                repo_url_override=repo_url_override,
            )
            response = client.post(
                f"{normalized_ingestion_url}/index",
                json=request.model_dump(mode="json", exclude_none=True),
            )
            response.raise_for_status()
            accepted = IndexAcceptedResponse.model_validate(response.json())
            if accepted.workflow_ids:
                print(f"Accepted workflows: {', '.join(accepted.workflow_ids)}")

            wait_for_indexing(
                client=client,
                ingestion_url=normalized_ingestion_url,
                repos=[repo],
                initial_statuses=initial_statuses,
                allow_stale_terminal_statuses={repo.full_name},
                poll_interval_seconds=poll_interval_seconds,
                progress_heartbeat_seconds=progress_heartbeat_seconds,
                timeout_seconds=timeout_seconds,
            )

    return workspace.repo_registry_path.resolve()


def prepare_synthetic_wiki(
    *,
    workspace: PreparedSyntheticWorkspace,
    ingestion_url: str = DEFAULT_SYNTHETIC_WIKI_INGESTION_URL,
    poll_interval_seconds: float = DEFAULT_WIKI_POLL_INTERVAL_SECONDS,
    progress_heartbeat_seconds: float = DEFAULT_WIKI_PROGRESS_HEARTBEAT_SECONDS,
    timeout_seconds: float = DEFAULT_WIKI_TIMEOUT_SECONDS,
) -> None:
    if not ingestion_url.strip():
        raise ValueError("ingestion_url must not be empty.")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be greater than 0.")
    if progress_heartbeat_seconds <= 0:
        raise ValueError("progress_heartbeat_seconds must be greater than 0.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than 0.")

    repo = shared_repo_entry(workspace)
    full_name = shared_resolved_repository(workspace).full_name
    normalized_ingestion_url = ingestion_url.rstrip("/")

    with httpx.Client(
        timeout=30.0, headers=_build_internal_service_headers()
    ) as client:
        status = get_wiki_status(
            client=client,
            ingestion_url=normalized_ingestion_url,
            github_repo_id=repo.github_repo_id,
            branch=repo.branch,
        )
        normalized_status = normalize_wiki_status(status.status if status else None)

        if normalized_status == "completed":
            page_count = 0 if status is None else status.page_count
            print(
                f"Wiki already generated: {full_name}@{repo.branch} ({page_count} page(s))"
            )
            return

        repos_to_wait_for = {full_name: repo}
        if normalized_status in ACTIVE_WIKI_STATUSES:
            print(f"Wiki already generating: {full_name}@{repo.branch}")
        else:
            request = build_synthetic_wiki_request(workspace)
            accepted = submit_wiki_generation_request(
                client=client,
                ingestion_url=normalized_ingestion_url,
                github_repo_id=request.github_repo_id,
                branch=request.branch,
                repo_display_name=f"{full_name}@{repo.branch}",
            )
            print(
                f"Started wiki generation for {full_name}@{repo.branch} "
                f"({accepted.workflow_id})"
            )

        wait_for_wiki_generation(
            client=client,
            ingestion_url=normalized_ingestion_url,
            repos=repos_to_wait_for,
            poll_interval_seconds=poll_interval_seconds,
            progress_heartbeat_seconds=progress_heartbeat_seconds,
            timeout_seconds=timeout_seconds,
        )


def build_synthetic_lighthouse_messages(
    *,
    workspace: PreparedSyntheticWorkspace,
    search_service_url: str = DEFAULT_SEARCH_SERVICE_URL,
    top_k: int = DEFAULT_SEARCH_TOP_K,
    context_source: str = DEFAULT_SYNTHETIC_CONTEXT_SOURCE,
) -> dict[str, str]:
    if top_k < 1:
        raise ValueError("top_k must be at least 1.")
    if context_source not in {"code", "wiki"}:
        raise ValueError("context_source must be either 'code' or 'wiki'.")
    if not search_service_url.strip():
        raise ValueError("search_service_url must not be empty.")

    repo_entry = shared_repo_entry(workspace)
    normalized_search_url = search_service_url.rstrip("/")
    messages: dict[str, str] = {}

    with httpx.Client(
        timeout=30.0, headers=_build_internal_service_headers()
    ) as client:
        for index, prepared in enumerate(workspace.tasks, start=1):
            task = prepared.task
            print(
                f"[{index}/{len(workspace.tasks)}] Retrieving synthetic context for {task.task_id}"
            )
            if context_source == "code":
                result = search_synthetic_code(
                    client=client,
                    search_service_url=normalized_search_url,
                    workspace=workspace,
                    task=task,
                    top_k=top_k,
                )
                print(f"    retrieved {len(result.snippets)} code snippet(s)")
                messages[task.task_id] = build_synthetic_code_lighthouse_user_message(
                    prepared, result.snippets
                )
            else:
                result = search_synthetic_wiki(
                    client=client,
                    search_service_url=normalized_search_url,
                    workspace=workspace,
                    task=task,
                    top_k=top_k,
                )
                print(f"    retrieved {len(result.snippets)} wiki snippet(s)")
                messages[task.task_id] = build_synthetic_wiki_lighthouse_user_message(
                    prepared, result.snippets
                )
            print(
                "    repo target: "
                f"{shared_resolved_repository(workspace).full_name} "
                f"(github_repo_id={repo_entry.github_repo_id}, branch={repo_entry.branch})"
            )

    return messages


def search_synthetic_code(
    *,
    client: httpx.Client,
    search_service_url: str,
    workspace: PreparedSyntheticWorkspace,
    task: SyntheticTask,
    top_k: int,
) -> SearchResult:
    repo_entry = shared_repo_entry(workspace)
    request = SearchRequest(
        query=build_synthetic_search_query(task),
        github_repo_id=repo_entry.github_repo_id,
        branch=repo_entry.branch,
        top_k=top_k,
    )
    response = client.post(
        f"{search_service_url}/search",
        json=request.model_dump(mode="json", exclude_none=True),
    )
    _raise_for_search_response(response, context_label="synthetic code")
    return SearchResult.model_validate(response.json())


def search_synthetic_wiki(
    *,
    client: httpx.Client,
    search_service_url: str,
    workspace: PreparedSyntheticWorkspace,
    task: SyntheticTask,
    top_k: int,
) -> WikiSearchResult:
    repo_entry = shared_repo_entry(workspace)
    request = WikiSearchRequest(
        query=build_synthetic_search_query(task),
        github_repo_id=repo_entry.github_repo_id,
        branch=repo_entry.branch,
        top_k=top_k,
    )
    response = client.post(
        f"{search_service_url}/search",
        json=request.model_dump(mode="json", exclude_none=True),
    )
    _raise_for_search_response(response, context_label="synthetic wiki")
    return WikiSearchResult.model_validate(response.json())


def _build_internal_service_headers() -> dict[str, str]:
    token = os.environ.get("INTERNAL_SERVICE_TOKEN", "").strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _is_local_service_url(url: str) -> bool:
    normalized = url if "://" in url else f"http://{url}"
    parsed = httpx.URL(normalized)
    host = (parsed.host or "").strip().lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _raise_for_search_response(response: httpx.Response, *, context_label: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text.strip()
        if len(detail) > 200:
            detail = detail[:197] + "..."
        hint = (
            f"Search service request failed during {context_label} retrieval "
            f"({response.status_code} {response.reason_phrase})."
        )
        if response.status_code >= 500:
            hint += (
                " The search service may be running against an out-of-date database schema. "
                "If the service logs mention missing relations such as 'indexed_files' or "
                "wiki tables, run the DB migrations in packages/db and retry."
            )
        if detail:
            hint += f" Response body: {detail}"
        raise RuntimeError(hint) from exc
