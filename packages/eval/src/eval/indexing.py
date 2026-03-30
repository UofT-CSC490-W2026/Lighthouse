from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

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
DEFAULT_STATUS_TIMEOUT_SECONDS = 5_400.0
DEFAULT_PROGRESS_HEARTBEAT_SECONDS = 30.0
DEFAULT_INTERNAL_SERVICE_TOKEN_ENV_VAR = "INTERNAL_SERVICE_TOKEN"
ACTIVE_INDEX_STATUSES = {"indexing", "pending", "in_progress"}


@dataclass(frozen=True)
class ResolvedRepository:
    full_name: str
    github_repo_id: int
    repo_url: str
    branch: str


class IngestionWorkerLogStreamer(AbstractContextManager["IngestionWorkerLogStreamer"]):
    def __init__(self, *, compose_root: Path | None, enabled: bool) -> None:
        self.compose_root = compose_root
        self.enabled = enabled
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> IngestionWorkerLogStreamer:
        if not self.enabled:
            return self
        if self.compose_root is None:
            print(
                "Skipping ingestion-worker log streaming because no Docker Compose "
                "project root was found."
            )
            return self

        since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            self._process = subprocess.Popen(
                [
                    "docker",
                    "compose",
                    "logs",
                    "--no-color",
                    "--follow",
                    "--since",
                    since,
                    "ingestion-worker",
                ],
                cwd=str(self.compose_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            print("Skipping ingestion-worker log streaming because Docker is not installed.")
            self._process = None
            return self
        except OSError as exc:
            print(f"Skipping ingestion-worker log streaming: {exc}")
            self._process = None
            return self

        print("Streaming local ingestion-worker logs while indexing...")
        self._thread = threading.Thread(target=self._pump_output, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        process = self._process
        if process is None:
            return None

        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1)
        return None

    def _pump_output(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if not line:
                continue
            print(f"[ingestion-worker] {line}", flush=True)


def index_swebench_repositories(
    *,
    tasks: list[SWEBenchTask],
    ingestion_url: str = DEFAULT_INGESTION_URL,
    output_path: Path = DEFAULT_REPO_REGISTRY_OUTPUT,
    github_token: str | None = None,
    stream_worker_logs: bool | None = None,
    poll_interval_seconds: float = DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
    progress_heartbeat_seconds: float = DEFAULT_PROGRESS_HEARTBEAT_SECONDS,
    timeout_seconds: float = DEFAULT_STATUS_TIMEOUT_SECONDS,
) -> Path:
    if not tasks:
        raise ValueError("No SWE-bench tasks selected for repository indexing.")
    if not ingestion_url.strip():
        raise ValueError("ingestion_url must not be empty.")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be greater than 0.")
    if progress_heartbeat_seconds <= 0:
        raise ValueError("progress_heartbeat_seconds must be greater than 0.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than 0.")

    token = github_token or os.environ.get("GITHUB_TOKEN")
    resolved_repos = resolve_repositories(tasks=tasks, github_token=token)
    normalized_ingestion_url = ingestion_url.rstrip("/")
    compose_root = find_compose_project_root(Path.cwd())
    should_stream_logs = resolve_stream_worker_logs_setting(
        stream_worker_logs=stream_worker_logs,
        ingestion_url=normalized_ingestion_url,
        compose_root=compose_root,
    )

    with IngestionWorkerLogStreamer(
        compose_root=compose_root,
        enabled=should_stream_logs,
    ):
        with httpx.Client(
            timeout=30.0,
            headers=_build_internal_service_headers(),
        ) as client:
            already_indexed: dict[str, ResolvedRepository] = {}
            already_indexing: dict[str, ResolvedRepository] = {}
            to_index: list[ResolvedRepository] = []
            initial_statuses: dict[str, str | None] = {}

            for repo in resolved_repos:
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
                    already_indexed[repo.full_name] = repo
                elif branch_status in ACTIVE_INDEX_STATUSES:
                    print(f"Already indexing: {repo.full_name}@{repo.branch}")
                    already_indexing[repo.full_name] = repo
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
            elif already_indexing:
                print("Selected repositories already have indexing in progress.")
            else:
                print(
                    "All selected repositories are already indexed for the requested branches."
                )

            if to_index or already_indexing:
                wait_for_indexing(
                    client=client,
                    ingestion_url=normalized_ingestion_url,
                    repos=[*already_indexing.values(), *to_index],
                    initial_statuses=initial_statuses,
                    allow_stale_terminal_statuses={
                        repo.full_name for repo in to_index
                    },
                    poll_interval_seconds=poll_interval_seconds,
                    progress_heartbeat_seconds=progress_heartbeat_seconds,
                    timeout_seconds=timeout_seconds,
                )

    registry = {
        repo.full_name: RepoRegistryEntry(
            github_repo_id=repo.github_repo_id,
            branch=repo.branch,
        )
        for repo in resolved_repos
    }
    write_repo_registry(output_path=output_path, registry=registry)
    return output_path.resolve()


def _build_internal_service_headers() -> dict[str, str]:
    token = os.environ.get(DEFAULT_INTERNAL_SERVICE_TOKEN_ENV_VAR, "").strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


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


def normalize_branch_status(status: str | None) -> str | None:
    if status is None:
        return None
    return status.strip().lower()


def resolve_stream_worker_logs_setting(
    *,
    stream_worker_logs: bool | None,
    ingestion_url: str,
    compose_root: Path | None,
) -> bool:
    if stream_worker_logs is not None:
        return stream_worker_logs
    if compose_root is None:
        return False

    parsed = urlparse(ingestion_url if "://" in ingestion_url else f"http://{ingestion_url}")
    hostname = (parsed.hostname or "").strip().lower()
    return hostname in {"localhost", "127.0.0.1", "::1"}


def find_compose_project_root(start: Path) -> Path | None:
    current = start.resolve()
    candidates = ("docker-compose.yml", "compose.yml", "compose.yaml")
    for directory in (current, *current.parents):
        if any((directory / candidate).exists() for candidate in candidates):
            return directory
    return None


def wait_for_indexing(
    *,
    client: httpx.Client,
    ingestion_url: str,
    repos: list[ResolvedRepository],
    initial_statuses: dict[str, str | None],
    allow_stale_terminal_statuses: set[str],
    poll_interval_seconds: float,
    progress_heartbeat_seconds: float,
    timeout_seconds: float,
) -> None:
    start_time = time.monotonic()
    deadline = time.monotonic() + timeout_seconds
    pending = {repo.full_name: repo for repo in repos}
    last_seen_status: dict[str, str] = {}
    seen_live_progress: set[str] = set()
    last_heartbeat_at = start_time

    while pending:
        if time.monotonic() > deadline:
            pending_display = ", ".join(
                f"{repo.full_name}@{repo.branch}" for repo in pending.values()
            )
            raise TimeoutError(
                "Timed out while waiting for repository indexing to finish: "
                f"{pending_display}"
            )

        status_changed = False
        for full_name, repo in list(pending.items()):
            status = get_index_status(
                client=client,
                ingestion_url=ingestion_url,
                github_repo_id=repo.github_repo_id,
            )
            branch_status = normalize_branch_status(
                branch_status_for(status, repo.branch) if status is not None else None
            )
            normalized_status = branch_status or "pending"

            if last_seen_status.get(full_name) != normalized_status:
                print(f"Index status: {repo.full_name}@{repo.branch} -> {normalized_status}")
                last_seen_status[full_name] = normalized_status
                status_changed = True

            if normalized_status in ACTIVE_INDEX_STATUSES or normalized_status == "indexed":
                seen_live_progress.add(full_name)

            if normalized_status == "indexed":
                pending.pop(full_name)
                continue

            if normalized_status in {"failed", "error"}:
                initial_status = initial_statuses.get(full_name)
                if (
                    full_name in allow_stale_terminal_statuses
                    and full_name not in seen_live_progress
                    and initial_status in {"failed", "error"}
                    and normalized_status == initial_status
                ):
                    continue
                raise RuntimeError(
                    f"Repository indexing failed for {repo.full_name}@{repo.branch}"
                )

        if pending:
            now = time.monotonic()
            if not status_changed and now - last_heartbeat_at >= progress_heartbeat_seconds:
                elapsed = format_elapsed(now - start_time)
                pending_display = ", ".join(
                    f"{repo.full_name}@{repo.branch}={last_seen_status.get(full_name, 'pending')}"
                    for full_name, repo in pending.items()
                )
                print(f"Still waiting after {elapsed}: {pending_display}")
                sys.stdout.flush()
                last_heartbeat_at = now
            time.sleep(poll_interval_seconds)


def format_elapsed(seconds: float) -> str:
    total_seconds = max(int(seconds), 0)
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, remaining_minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {remaining_minutes}m {remaining_seconds}s"
    if minutes:
        return f"{minutes}m {remaining_seconds}s"
    return f"{remaining_seconds}s"


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
