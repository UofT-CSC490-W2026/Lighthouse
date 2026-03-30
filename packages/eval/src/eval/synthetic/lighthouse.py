from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

import httpx
from pydantic import ValidationError
from shared.schemas.ingestion import IndexAcceptedResponse
from shared.schemas.search import (
    CodeSnippet,
    CombinedSearchResult,
    CombinedSnippet,
    SearchRequest,
    SearchContextSource,
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
    ResolvedRepository,
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
    build_synthetic_ast_lighthouse_user_message,
    build_synthetic_combined_lighthouse_user_message,
    build_synthetic_code_lighthouse_user_message,
    build_synthetic_search_query,
    build_synthetic_wiki_lighthouse_user_message,
)
from .workspace import (
    PreparedSyntheticWorkspace,
    SyntheticSearchRepository,
    SyntheticTask,
    ast_resolved_repository,
    build_synthetic_index_request_for_repositories,
    build_synthetic_wiki_request,
    shared_repo_entry,
    shared_resolved_repository,
    synthetic_search_repositories,
    synthetic_repo_url_for_container,
)

DEFAULT_SYNTHETIC_WIKI_INGESTION_URL = DEFAULT_INGESTION_URL
DEFAULT_SYNTHETIC_CONTEXT_SOURCE = "code"
_GREP_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def index_synthetic_repository(
    *,
    workspace: PreparedSyntheticWorkspace,
    ingestion_url: str = DEFAULT_INGESTION_URL,
    github_token: str | None = None,
    stream_worker_logs: bool | None = None,
    poll_interval_seconds: float = DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
    progress_heartbeat_seconds: float = DEFAULT_PROGRESS_HEARTBEAT_SECONDS,
    timeout_seconds: float = DEFAULT_STATUS_TIMEOUT_SECONDS,
    include_ast: bool = False,
    embedding_strategy: str | None = None,
    embedding_model: str | None = None,
) -> Path:
    if not ingestion_url.strip():
        raise ValueError("ingestion_url must not be empty.")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be greater than 0.")
    if progress_heartbeat_seconds <= 0:
        raise ValueError("progress_heartbeat_seconds must be greater than 0.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than 0.")

    repositories = synthetic_search_repositories(workspace, include_ast=include_ast)
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
            initial_statuses: dict[str, str | None] = {}
            to_wait = []
            to_submit = []
            for repo in repositories:
                status = get_index_status(
                    client=client,
                    ingestion_url=normalized_ingestion_url,
                    github_repo_id=repo.github_repo_id,
                )
                branch_status = normalize_branch_status(
                    branch_status_for(status, repo.branch) if status is not None else None
                )
                initial_statuses[repo.full_name] = branch_status
                if branch_status == "indexed":
                    print(f"Already indexed: {repo.full_name}@{repo.branch}")
                elif branch_status in ACTIVE_INDEX_STATUSES:
                    print(f"Already indexing: {repo.full_name}@{repo.branch}")
                    to_wait.append(repo)
                else:
                    to_submit.append(repo)

            if not to_submit and not to_wait:
                return workspace.repo_registry_path.resolve()

            repo_url_override: str | None = None
            if compose_root is not None and _is_local_service_url(
                normalized_ingestion_url
            ):
                repo_url_override = synthetic_repo_url_for_container(
                    workspace,
                    compose_root=compose_root,
                )
                print(f"Using container-visible repo path: {repo_url_override}")
            if to_submit:
                display = ", ".join(
                    f"{repo.full_name}@{repo.branch}" for repo in to_submit
                )
                print(f"Submitting synthetic indexing request for {display}")
                request = build_synthetic_index_request_for_repositories(
                    tuple(to_submit),
                    github_token=github_token,
                    repo_url_override=repo_url_override,
                    embedding_strategy=embedding_strategy,
                    embedding_model=embedding_model,
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
                repos=[
                    _as_resolved_repository(repo) for repo in [*to_wait, *to_submit]
                ],
                initial_statuses=initial_statuses,
                allow_stale_terminal_statuses={repo.full_name for repo in to_submit},
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
    embedding_strategy: str | None = None,
    embedding_model: str | None = None,
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
            request = build_synthetic_wiki_request(
                workspace,
                embedding_strategy=embedding_strategy,
                embedding_model=embedding_model,
            )
            accepted = submit_wiki_generation_request(
                client=client,
                ingestion_url=normalized_ingestion_url,
                github_repo_id=request.github_repo_id,
                branch=request.branch,
                embedding_strategy=request.embedding_strategy,
                embedding_model=request.embedding_model,
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
    query_embedding_strategy: str | None = None,
    query_embedding_model: str | None = None,
) -> dict[str, str]:
    if top_k < 1:
        raise ValueError("top_k must be at least 1.")
    if context_source not in {"code", "wiki", "ast", "combined", "code+wiki", "grep"}:
        raise ValueError(
            "context_source must be 'code', 'wiki', 'ast', 'combined', 'code+wiki', or 'grep'."
        )
    if context_source == "grep":
        return build_synthetic_grep_messages(workspace=workspace, top_k=top_k)
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
                    embedding_strategy=query_embedding_strategy,
                    embedding_model=query_embedding_model,
                )
                print(f"    retrieved {len(result.snippets)} code snippet(s)")
                messages[task.task_id] = build_synthetic_code_lighthouse_user_message(
                    prepared, result.snippets
                )
            elif context_source == "wiki":
                result = search_synthetic_wiki(
                    client=client,
                    search_service_url=normalized_search_url,
                    workspace=workspace,
                    task=task,
                    top_k=top_k,
                    embedding_strategy=query_embedding_strategy,
                    embedding_model=query_embedding_model,
                )
                print(f"    retrieved {len(result.snippets)} wiki snippet(s)")
                messages[task.task_id] = build_synthetic_wiki_lighthouse_user_message(
                    prepared, result.snippets
                )
            elif context_source == "ast":
                result = search_synthetic_ast(
                    client=client,
                    search_service_url=normalized_search_url,
                    workspace=workspace,
                    task=task,
                    top_k=top_k,
                    embedding_strategy=query_embedding_strategy,
                    embedding_model=query_embedding_model,
                )
                print(f"    retrieved {len(result.snippets)} ast snippet(s)")
                messages[task.task_id] = build_synthetic_ast_lighthouse_user_message(
                    prepared, result.snippets
                )
            elif context_source == "code+wiki":
                result = search_synthetic_code_and_wiki(
                    client=client,
                    search_service_url=normalized_search_url,
                    workspace=workspace,
                    task=task,
                    top_k=top_k,
                    embedding_strategy=query_embedding_strategy,
                    embedding_model=query_embedding_model,
                )
                print(f"    retrieved {len(result.snippets)} fused snippet(s)")
                messages[task.task_id] = build_synthetic_combined_lighthouse_user_message(
                    prepared, result.snippets
                )
            else:
                result = search_synthetic_combined(
                    client=client,
                    search_service_url=normalized_search_url,
                    workspace=workspace,
                    task=task,
                    top_k=top_k,
                    embedding_strategy=query_embedding_strategy,
                    embedding_model=query_embedding_model,
                )
                print(f"    retrieved {len(result.snippets)} fused snippet(s)")
                messages[task.task_id] = build_synthetic_combined_lighthouse_user_message(
                    prepared, result.snippets
                )
            print(
                "    repo target: "
                f"{shared_resolved_repository(workspace).full_name} "
                f"(github_repo_id={repo_entry.github_repo_id}, branch={repo_entry.branch})"
            )

    return messages


def build_synthetic_grep_messages(
    *,
    workspace: PreparedSyntheticWorkspace,
    top_k: int,
) -> dict[str, str]:
    repo_root = workspace.search_repo_path.resolve()
    messages: dict[str, str] = {}
    for index, prepared in enumerate(workspace.tasks, start=1):
        task = prepared.task
        print(
            f"[{index}/{len(workspace.tasks)}] Retrieving synthetic context for {task.task_id} (grep)"
        )
        snippets = grep_synthetic_code(
            repo_root=repo_root,
            task=task,
            top_k=top_k,
        )
        print(f"    retrieved {len(snippets)} grep snippet(s)")
        messages[task.task_id] = build_synthetic_code_lighthouse_user_message(
            prepared,
            snippets,
        )
    return messages


def grep_synthetic_code(
    *,
    repo_root: Path,
    task: SyntheticTask,
    top_k: int,
) -> list[CodeSnippet]:
    if top_k < 1:
        return []

    terms = _grep_query_terms(task)
    if not terms:
        return []

    matched_terms_by_file: dict[Path, set[str]] = {}
    for term in terms:
        for file_path in _rg_files_for_term(repo_root=repo_root, term=term):
            matched_terms_by_file.setdefault(file_path, set()).add(term)

    ranked_paths = sorted(
        matched_terms_by_file,
        key=lambda path: (
            -len(matched_terms_by_file[path]),
            str(path),
        ),
    )
    snippets: list[CodeSnippet] = []
    for file_path in ranked_paths[:top_k]:
        matched_terms = sorted(matched_terms_by_file[file_path])
        snippet = _snippet_for_file(
            repo_root=repo_root,
            file_path=file_path,
            matched_terms=matched_terms,
        )
        if snippet is not None:
            snippets.append(snippet)
    return snippets


def _grep_query_terms(task: SyntheticTask) -> tuple[str, ...]:
    ordered_terms: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        normalized = term.strip()
        if len(normalized) < 3:
            return
        key = normalized.lower()
        if key in seen:
            return
        seen.add(key)
        ordered_terms.append(normalized)

    for symbol in task.expected_relevant_symbols:
        _add(symbol)
    for api_name in task.visible_api_names:
        _add(api_name)

    for token in _GREP_TOKEN_RE.findall(
        f"{task.title}\n{task.problem_statement}\n{task.test_context}"
    ):
        if token.lower() in {"the", "and", "for", "with", "from", "that", "this"}:
            continue
        _add(token)
        if len(ordered_terms) >= 12:
            break

    return tuple(ordered_terms[:12])


def _rg_files_for_term(*, repo_root: Path, term: str) -> tuple[Path, ...]:
    command = [
        "rg",
        "--files-with-matches",
        "-S",
        "--glob",
        "*.py",
        "--glob",
        "!**/tests/**",
        "--glob",
        "!**/.venv/**",
        term,
        str(repo_root),
    ]
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode not in {0, 1}:
        return ()
    paths: list[Path] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        path = Path(line)
        if path.is_file():
            paths.append(path)
    return tuple(paths)


def _snippet_for_file(
    *,
    repo_root: Path,
    file_path: Path,
    matched_terms: list[str],
) -> CodeSnippet | None:
    try:
        text = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    lines = text.splitlines()
    if not lines:
        return None
    match_line_index = _first_matching_line_index(lines=lines, terms=matched_terms)
    if match_line_index is None:
        return None

    start_line = max(1, match_line_index + 1 - 8)
    end_line = min(len(lines), match_line_index + 1 + 8)
    content = "\n".join(lines[start_line - 1 : end_line]).rstrip()
    if not content:
        return None
    try:
        relative = file_path.relative_to(repo_root).as_posix()
    except ValueError:
        relative = file_path.as_posix()

    reason_terms = ", ".join(matched_terms[:3])
    return CodeSnippet(
        file_path=relative,
        start_line=start_line,
        end_line=end_line,
        content=content,
        language="python",
        score=float(len(matched_terms)),
        reason=f"grep match: {reason_terms}",
    )


def _first_matching_line_index(*, lines: list[str], terms: list[str]) -> int | None:
    lowered_terms = [term.lower() for term in terms]
    for index, line in enumerate(lines):
        if any(term in line for term in terms):
            return index
        lowered_line = line.lower()
        if any(term in lowered_line for term in lowered_terms):
            return index
    return None


def search_synthetic_code(
    *,
    client: httpx.Client,
    search_service_url: str,
    workspace: PreparedSyntheticWorkspace,
    task: SyntheticTask,
    top_k: int,
    embedding_strategy: str | None = None,
    embedding_model: str | None = None,
) -> SearchResult:
    repo_entry = shared_repo_entry(workspace)
    request = SearchRequest(
        query=build_synthetic_search_query(task),
        github_repo_id=repo_entry.github_repo_id,
        branch=repo_entry.branch,
        top_k=top_k,
        embedding_strategy=embedding_strategy,
        embedding_model=embedding_model,
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
    embedding_strategy: str | None = None,
    embedding_model: str | None = None,
) -> WikiSearchResult:
    repo_entry = shared_repo_entry(workspace)
    request = WikiSearchRequest(
        query=build_synthetic_search_query(task),
        github_repo_id=repo_entry.github_repo_id,
        branch=repo_entry.branch,
        top_k=top_k,
        embedding_strategy=embedding_strategy,
        embedding_model=embedding_model,
    )
    response = client.post(
        f"{search_service_url}/search",
        json=request.model_dump(mode="json", exclude_none=True),
    )
    _raise_for_search_response(response, context_label="synthetic wiki")
    return WikiSearchResult.model_validate(response.json())


def search_synthetic_ast(
    *,
    client: httpx.Client,
    search_service_url: str,
    workspace: PreparedSyntheticWorkspace,
    task: SyntheticTask,
    top_k: int,
    embedding_strategy: str | None = None,
    embedding_model: str | None = None,
) -> SearchResult:
    repo = ast_resolved_repository(workspace)
    request = SearchRequest(
        query=build_synthetic_search_query(task),
        github_repo_id=repo.github_repo_id,
        branch=repo.branch,
        top_k=top_k,
        embedding_strategy=embedding_strategy,
        embedding_model=embedding_model,
    )
    response = client.post(
        f"{search_service_url}/search",
        json=request.model_dump(mode="json", exclude_none=True),
    )
    _raise_for_search_response(response, context_label="synthetic ast")
    return SearchResult.model_validate(response.json())


def search_synthetic_code_and_wiki(
    *,
    client: httpx.Client,
    search_service_url: str,
    workspace: PreparedSyntheticWorkspace,
    task: SyntheticTask,
    top_k: int,
    embedding_strategy: str | None = None,
    embedding_model: str | None = None,
) -> CombinedSearchResult:
    repo_entry = shared_repo_entry(workspace)
    request = SearchRequest(
        query=build_synthetic_search_query(task),
        github_repo_id=repo_entry.github_repo_id,
        branch=repo_entry.branch,
        top_k=top_k,
        embedding_strategy=embedding_strategy,
        embedding_model=embedding_model,
        context_sources=(
            SearchContextSource.code,
            SearchContextSource.wiki,
        ),
    )
    response = client.post(
        f"{search_service_url}/search",
        json=request.model_dump(mode="json", exclude_none=True),
    )
    _raise_for_search_response(response, context_label="synthetic code+wiki")
    try:
        return CombinedSearchResult.model_validate(response.json())
    except ValidationError as exc:
        payload = response.json()
        snippets = payload.get("snippets") if isinstance(payload, dict) else None
        if isinstance(snippets, list) and snippets:
            first = snippets[0]
            if isinstance(first, dict) and "context_source" not in first:
                raise RuntimeError(
                    "Search service returned a single-source snippet payload during "
                    "synthetic code+wiki retrieval. The running search service is "
                    "likely still on the old build and needs to be rebuilt/restarted "
                    "so /search can return fused code+wiki results."
                ) from exc
        raise


def search_synthetic_combined(
    *,
    client: httpx.Client,
    search_service_url: str,
    workspace: PreparedSyntheticWorkspace,
    task: SyntheticTask,
    top_k: int,
    embedding_strategy: str | None = None,
    embedding_model: str | None = None,
) -> CombinedSearchResult:
    code_result = search_synthetic_code(
        client=client,
        search_service_url=search_service_url,
        workspace=workspace,
        task=task,
        top_k=top_k,
        embedding_strategy=embedding_strategy,
        embedding_model=embedding_model,
    )
    wiki_result = search_synthetic_wiki(
        client=client,
        search_service_url=search_service_url,
        workspace=workspace,
        task=task,
        top_k=top_k,
        embedding_strategy=embedding_strategy,
        embedding_model=embedding_model,
    )
    ast_result = search_synthetic_ast(
        client=client,
        search_service_url=search_service_url,
        workspace=workspace,
        task=task,
        top_k=top_k,
        embedding_strategy=embedding_strategy,
        embedding_model=embedding_model,
    )
    fused = _rrf_fuse_combined(
        [
            _normalize_code_result(code_result, SearchContextSource.code),
            _normalize_wiki_result(wiki_result),
            _normalize_code_result(ast_result, SearchContextSource.ast),
        ]
    )
    return CombinedSearchResult(
        snippets=fused[:top_k],
        query=build_synthetic_search_query(task),
        total_results=len(fused),
    )


def _normalize_code_result(
    result: SearchResult,
    context_source: SearchContextSource,
) -> list[CombinedSnippet]:
    return [
        CombinedSnippet(
            context_source=context_source,
            content=snippet.content,
            score=snippet.score,
            file_path=snippet.file_path,
            start_line=snippet.start_line,
            end_line=snippet.end_line,
            reason=snippet.reason,
        )
        for snippet in result.snippets
    ]


def _normalize_wiki_result(result: WikiSearchResult) -> list[CombinedSnippet]:
    return [
        CombinedSnippet(
            context_source=SearchContextSource.wiki,
            content=snippet.content_snippet,
            score=snippet.score,
            page_title=snippet.page_title,
            slug=snippet.slug,
            section_path=snippet.section_path,
        )
        for snippet in result.snippets
    ]


def _rrf_fuse_combined(
    ranked_lists: list[list[CombinedSnippet]],
    *,
    k: int = 60,
) -> list[CombinedSnippet]:
    scores: dict[str, float] = {}
    snippet_map: dict[str, CombinedSnippet] = {}

    for ranked in ranked_lists:
        for rank, snippet in enumerate(ranked):
            key = _combined_snippet_key(snippet)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            snippet_map.setdefault(key, snippet)

    return [
        snippet_map[key].model_copy(update={"score": scores[key]})
        for key in sorted(scores, key=lambda item: scores[item], reverse=True)
    ]


def _combined_snippet_key(snippet: CombinedSnippet) -> str:
    if snippet.context_source in {SearchContextSource.code, SearchContextSource.ast}:
        return (
            f"{snippet.context_source.value}:{snippet.file_path or ''}:"
            f"{snippet.start_line or 0}:{snippet.end_line or 0}"
        )
    return (
        f"wiki:{snippet.slug or ''}:"
        f"{snippet.section_path or ''}:{snippet.page_title or ''}"
    )


def _as_resolved_repository(repo: SyntheticSearchRepository) -> ResolvedRepository:
    return ResolvedRepository(
        full_name=repo.full_name,
        github_repo_id=repo.github_repo_id,
        repo_url=repo.repo_url,
        branch=repo.branch,
    )


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
