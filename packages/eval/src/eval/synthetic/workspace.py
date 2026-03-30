from __future__ import annotations

from collections.abc import Mapping
import json
import random
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from shared.schemas.ingestion import IndexRequest, RepoIndexRequest
from shared.schemas.wiki import GenerateWikiRequest

from eval.indexing import ResolvedRepository
from eval.lighthouse import RepoRegistryEntry

DEFAULT_SYNTHETIC_FAMILY = "synthetic-ab-contracts"
DEFAULT_SYNTHETIC_WORKSPACE_ROOT = Path(".cache/eval/synthetic")
DEFAULT_SYNTHETIC_RUNS_ROOT = Path(".cache/eval/synthetic_runs")
DEFAULT_SYNTHETIC_TASK_TYPE = "api_contract_mismatch"
SUPPORTED_SYNTHETIC_TASK_TYPES = frozenset({
    DEFAULT_SYNTHETIC_TASK_TYPE,
    "logic_wrong_operator",
    "data_type_coercion",
    "doc_behavior_mismatch",
    "feature_api_integration",
    "feature_doc_guided",
})
REPAIR_TASK_TYPES = frozenset({
    DEFAULT_SYNTHETIC_TASK_TYPE,
    "logic_wrong_operator",
    "data_type_coercion",
    "doc_behavior_mismatch",
})
FEATURE_TASK_TYPES = frozenset({
    "feature_api_integration",
    "feature_doc_guided",
})
DEFAULT_SYNTHETIC_BRANCH = "main"
DEFAULT_SYNTHETIC_CONTAINER_PROJECT_ROOT = Path("/workspace")
DEFAULT_AST_CHUNKER_STRATEGY = "ast_code"
DEFAULT_BASE_CHUNKER_STRATEGY = "sliding_window"
_AST_REPO_ID_OFFSET = 100_000_000
_AST_REPO_NAME_SUFFIX = "-ast"
_FAMILY_CONFIG_FILENAME = "family.json"
_TASK_MANIFEST_FILENAME = "tasks.json"


@dataclass(frozen=True)
class SyntheticGenerationConfig:
    family_name: str
    family_version: str
    task_type: str
    task_count: int
    shared_library_repo_count: int
    consumer_repo_mode: str
    python_version_target: str
    context_modes: tuple[str, ...]
    seed: int


@dataclass(frozen=True)
class SyntheticTask:
    task_id: str
    task_type: str
    title: str
    problem_statement: str
    repo_a_name: str
    repo_b_name: str
    repo_a_id: int
    repo_b_id: int
    branch: str
    buggy_patch_path: Path
    gold_patch_path: Path
    pytest_targets: tuple[str, ...]
    expected_relevant_files: tuple[str, ...]
    expected_relevant_symbols: tuple[str, ...]
    context_modes_supported: tuple[str, ...]
    visible_api_names: tuple[str, ...]
    test_context: str
    consumer_edit_files: tuple[str, ...]
    consumer_test_files: tuple[str, ...]


@dataclass(frozen=True)
class SyntheticFamily:
    family_dir: Path
    config: SyntheticGenerationConfig
    tasks: tuple[SyntheticTask, ...]


@dataclass(frozen=True)
class PreparedSyntheticTask:
    task: SyntheticTask
    repo_a_path: Path


@dataclass(frozen=True)
class PreparedSyntheticWorkspace:
    family: SyntheticFamily
    workspace_dir: Path
    repo_b_path: Path | None
    repo_registry_path: Path
    selection_manifest_path: Path
    validation_report_path: Path
    tasks: tuple[PreparedSyntheticTask, ...]
    seed: int

    @property
    def has_shared_repo(self) -> bool:
        return self.repo_b_path is not None

    @property
    def search_repo_path(self) -> Path:
        """Path to the repo indexed for search/wiki/AST (repo_b or canonical clean repo_a)."""
        if self.repo_b_path is not None:
            return self.repo_b_path
        return self.workspace_dir / "repos" / "repo_a"


@dataclass(frozen=True)
class SyntheticSearchRepository:
    full_name: str
    github_repo_id: int
    repo_url: str
    branch: str
    chunker_strategy: str | None = None


def load_synthetic_family(
    family_name: str = DEFAULT_SYNTHETIC_FAMILY,
) -> SyntheticFamily:
    family_dir = _family_dir_for_name(family_name)
    config_path = family_dir / _FAMILY_CONFIG_FILENAME
    manifest_path = family_dir / _TASK_MANIFEST_FILENAME
    if not config_path.is_file():
        raise FileNotFoundError(f"Synthetic family config not found: {config_path}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Synthetic family manifest not found: {manifest_path}")

    config_data = _load_json_object(config_path)
    manifest_data = _load_json_object(manifest_path)
    config = _parse_generation_config(config_data)

    manifest_family_name = str(manifest_data.get("family_name", "")).strip()
    manifest_family_version = str(manifest_data.get("family_version", "")).strip()
    if manifest_family_name != config.family_name:
        raise ValueError(
            "Synthetic family manifest name does not match config: "
            f"{manifest_family_name!r} != {config.family_name!r}"
        )
    if manifest_family_version != config.family_version:
        raise ValueError(
            "Synthetic family manifest version does not match config: "
            f"{manifest_family_version!r} != {config.family_version!r}"
        )

    generation_config_data = manifest_data.get("generation_config")
    if not isinstance(generation_config_data, Mapping):
        raise ValueError("Synthetic family manifest is missing generation_config.")
    manifest_generation_config = _as_mapping(generation_config_data)
    _validate_manifest_generation_config(manifest_generation_config, config)

    raw_tasks = manifest_data.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("Synthetic family manifest must contain a non-empty tasks list.")

    tasks = tuple(_parse_task(family_dir, raw_task) for raw_task in raw_tasks)
    return SyntheticFamily(family_dir=family_dir, config=config, tasks=tasks)


def select_synthetic_tasks(
    *,
    family_name: str = DEFAULT_SYNTHETIC_FAMILY,
    task_count: int | None = None,
    task_type: str | None = None,
    seed: int | None = None,
    shared_library_repo_count: int | None = None,
) -> tuple[SyntheticFamily, tuple[SyntheticTask, ...], int]:
    family = load_synthetic_family(family_name)
    effective_task_type = (task_type or family.config.task_type).strip()
    if effective_task_type != family.config.task_type:
        raise ValueError(
            "Unsupported synthetic task type. "
            f"Expected {family.config.task_type!r}, found {effective_task_type!r}."
        )
    if effective_task_type not in SUPPORTED_SYNTHETIC_TASK_TYPES:
        raise ValueError(f"Unsupported synthetic task type: {effective_task_type!r}")

    effective_shared_repo_count = (
        shared_library_repo_count
        if shared_library_repo_count is not None
        else family.config.shared_library_repo_count
    )
    if effective_shared_repo_count not in (0, 1):
        raise NotImplementedError(
            "Synthetic shared_library_repo_count values other than 0 or 1 are not supported."
        )

    effective_task_count = task_count if task_count is not None else family.config.task_count
    if effective_task_count < 1:
        raise ValueError("task_count must be at least 1.")
    if effective_task_count > len(family.tasks):
        raise ValueError(
            f"Requested {effective_task_count} synthetic tasks, but only "
            f"{len(family.tasks)} are available in {family_name!r}."
        )

    effective_seed = seed if seed is not None else family.config.seed
    if effective_task_count == len(family.tasks):
        return family, family.tasks, effective_seed

    shuffled = list(family.tasks)
    random.Random(effective_seed).shuffle(shuffled)
    selected_ids = {task.task_id for task in shuffled[:effective_task_count]}
    selected_tasks = tuple(task for task in family.tasks if task.task_id in selected_ids)
    return family, selected_tasks, effective_seed


def prepare_synthetic_workspace(
    *,
    family_name: str = DEFAULT_SYNTHETIC_FAMILY,
    task_count: int | None = None,
    task_type: str | None = None,
    seed: int | None = None,
    shared_library_repo_count: int | None = None,
    workspace_root: Path = DEFAULT_SYNTHETIC_WORKSPACE_ROOT,
    force: bool = False,
) -> PreparedSyntheticWorkspace:
    family, tasks, effective_seed = select_synthetic_tasks(
        family_name=family_name,
        task_count=task_count,
        task_type=task_type,
        seed=seed,
        shared_library_repo_count=shared_library_repo_count,
    )
    workspace_dir = (
        workspace_root.resolve()
        / _family_dir_name(family.config.family_name)
        / f"v{family.config.family_version}"
        / f"seed-{effective_seed}"
        / f"tasks-{len(tasks)}"
    )
    if force and workspace_dir.exists():
        shutil.rmtree(workspace_dir)

    has_shared_repo = family.config.shared_library_repo_count >= 1
    repo_b_path: Path | None = workspace_dir / "repos" / "repo_b" if has_shared_repo else None
    repo_registry_path = workspace_dir / "repo-registry.json"
    selection_manifest_path = workspace_dir / "prepared.json"
    validation_report_path = workspace_dir / "validation.json"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    if _workspace_requires_refresh(
        workspace_dir=workspace_dir,
        selection_manifest_path=selection_manifest_path,
        family_dir=family.family_dir,
    ):
        shutil.rmtree(workspace_dir)
        workspace_dir.mkdir(parents=True, exist_ok=True)

    if repo_b_path is not None and not repo_b_path.exists():
        _copy_tree(family.family_dir / "repo_b_template", repo_b_path)
        _initialize_git_repo(repo_b_path)

    if not has_shared_repo:
        canonical_repo_a = workspace_dir / "repos" / "repo_a"
        if not canonical_repo_a.exists():
            _copy_tree(family.family_dir / "repo_a_template", canonical_repo_a)
            _initialize_git_repo(canonical_repo_a)

    prepared_tasks: list[PreparedSyntheticTask] = []
    for task in tasks:
        repo_a_path = workspace_dir / "tasks" / task.task_id / "repo_a"
        if not repo_a_path.exists():
            _copy_tree(family.family_dir / "repo_a_template", repo_a_path)
            _initialize_git_repo(repo_a_path)
            if task.buggy_patch_path.stat().st_size > 0:
                _apply_patch(repo_a_path, task.buggy_patch_path)
        prepared_tasks.append(PreparedSyntheticTask(task=task, repo_a_path=repo_a_path))

    _write_repo_registry(repo_registry_path, tasks, has_shared_repo=has_shared_repo)
    _write_selection_manifest(
        selection_manifest_path=selection_manifest_path,
        validation_report_path=validation_report_path,
        family=family,
        tasks=prepared_tasks,
        repo_b_path=repo_b_path,
        repo_registry_path=repo_registry_path,
        seed=effective_seed,
    )

    return PreparedSyntheticWorkspace(
        family=family,
        workspace_dir=workspace_dir,
        repo_b_path=repo_b_path,
        repo_registry_path=repo_registry_path,
        selection_manifest_path=selection_manifest_path,
        validation_report_path=validation_report_path,
        tasks=tuple(prepared_tasks),
        seed=effective_seed,
    )


def build_task_lookup(tasks: tuple[PreparedSyntheticTask, ...]) -> dict[str, PreparedSyntheticTask]:
    return {prepared.task.task_id: prepared for prepared in tasks}


def shared_repo_entry(workspace: PreparedSyntheticWorkspace) -> RepoRegistryEntry:
    _name, repo_id, branch = _indexed_repo_identity_for_workspace(workspace)
    return RepoRegistryEntry(
        github_repo_id=repo_id,
        branch=branch,
    )


def shared_resolved_repository(workspace: PreparedSyntheticWorkspace) -> ResolvedRepository:
    name, repo_id, branch = _indexed_repo_identity_for_workspace(workspace)
    return ResolvedRepository(
        full_name=name,
        github_repo_id=repo_id,
        repo_url=str(workspace.search_repo_path.resolve()),
        branch=branch,
    )


def ast_repo_entry(workspace: PreparedSyntheticWorkspace) -> RepoRegistryEntry:
    name, repo_id, branch = _indexed_repo_identity_for_workspace(workspace)
    return RepoRegistryEntry(
        github_repo_id=_ast_repo_id(repo_id),
        branch=branch,
    )


def ast_resolved_repository(workspace: PreparedSyntheticWorkspace) -> ResolvedRepository:
    name, repo_id, branch = _indexed_repo_identity_for_workspace(workspace)
    return ResolvedRepository(
        full_name=_ast_repo_name(name),
        github_repo_id=_ast_repo_id(repo_id),
        repo_url=str(workspace.search_repo_path.resolve()),
        branch=branch,
    )


def synthetic_search_repositories(
    workspace: PreparedSyntheticWorkspace,
    *,
    include_ast: bool = False,
) -> tuple[SyntheticSearchRepository, ...]:
    shared_repo = shared_resolved_repository(workspace)
    repositories = [
        SyntheticSearchRepository(
            full_name=shared_repo.full_name,
            github_repo_id=shared_repo.github_repo_id,
            repo_url=shared_repo.repo_url,
            branch=shared_repo.branch,
            chunker_strategy=DEFAULT_BASE_CHUNKER_STRATEGY,
        )
    ]
    if include_ast:
        ast_repo = ast_resolved_repository(workspace)
        repositories.append(
            SyntheticSearchRepository(
                full_name=ast_repo.full_name,
                github_repo_id=ast_repo.github_repo_id,
                repo_url=ast_repo.repo_url,
                branch=ast_repo.branch,
                chunker_strategy=DEFAULT_AST_CHUNKER_STRATEGY,
            )
        )
    return tuple(repositories)


def build_synthetic_index_request(
    workspace: PreparedSyntheticWorkspace,
    *,
    github_token: str | None = None,
    repo_url_override: str | None = None,
    include_ast: bool = False,
) -> IndexRequest:
    repositories = synthetic_search_repositories(
        workspace,
        include_ast=include_ast,
    )
    return build_synthetic_index_request_for_repositories(
        repositories,
        github_token=github_token,
        repo_url_override=repo_url_override,
    )


def build_synthetic_index_request_for_repositories(
    repositories: tuple[SyntheticSearchRepository, ...],
    *,
    github_token: str | None = None,
    repo_url_override: str | None = None,
) -> IndexRequest:
    return IndexRequest(
        repositories=[
            RepoIndexRequest(
                github_repo_id=repo.github_repo_id,
                repo_url=repo_url_override or repo.repo_url,
                full_name=repo.full_name,
                branches=[repo.branch],
                github_token=github_token,
                chunker_strategy=repo.chunker_strategy,
            )
            for repo in repositories
        ]
    )


def build_synthetic_wiki_request(workspace: PreparedSyntheticWorkspace) -> GenerateWikiRequest:
    entry = shared_repo_entry(workspace)
    return GenerateWikiRequest(
        github_repo_id=entry.github_repo_id,
        branch=entry.branch,
    )


def copy_prepared_task_repositories(
    *,
    prepared_task: PreparedSyntheticTask,
    repo_b_path: Path | None,
    destination_root: Path,
) -> tuple[Path, Path | None]:
    repo_a_destination = destination_root / "repo_a"
    if repo_a_destination.exists():
        shutil.rmtree(repo_a_destination)
    shutil.copytree(prepared_task.repo_a_path, repo_a_destination)

    repo_b_destination: Path | None = None
    if repo_b_path is not None:
        repo_b_destination = destination_root / "repo_b"
        if repo_b_destination.exists():
            shutil.rmtree(repo_b_destination)
        shutil.copytree(repo_b_path, repo_b_destination)

    return repo_a_destination, repo_b_destination


def write_validation_report(
    output_path: Path,
    payload: Mapping[str, object],
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def synthetic_repo_url_for_container(
    workspace: PreparedSyntheticWorkspace,
    *,
    compose_root: Path,
    container_project_root: Path = DEFAULT_SYNTHETIC_CONTAINER_PROJECT_ROOT,
) -> str:
    repo_path = workspace.search_repo_path.resolve()
    relative_repo_path = repo_path.relative_to(compose_root.resolve())
    return str((container_project_root / relative_repo_path).as_posix())


def _workspace_requires_refresh(
    *,
    workspace_dir: Path,
    selection_manifest_path: Path,
    family_dir: Path,
) -> bool:
    if not workspace_dir.exists():
        return False
    if not selection_manifest_path.is_file():
        return any(workspace_dir.iterdir())

    manifest_mtime = selection_manifest_path.stat().st_mtime
    newest_family_mtime = max(
        (
            path.stat().st_mtime
            for path in family_dir.rglob("*")
            if path.is_file()
        ),
        default=manifest_mtime,
    )
    return newest_family_mtime > manifest_mtime


def _family_dir_for_name(family_name: str) -> Path:
    family_dir = Path(__file__).resolve().parent / "families" / _family_dir_name(family_name)
    if not family_dir.is_dir():
        raise FileNotFoundError(f"Synthetic family directory not found: {family_dir}")
    return family_dir


def _family_dir_name(family_name: str) -> str:
    return family_name.replace("-", "_").strip()


def _load_json_object(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _parse_generation_config(data: Mapping[str, object]) -> SyntheticGenerationConfig:
    family_name = _string_value(data, "family_name")
    family_version = _string_value(data, "family_version")
    task_type = _string_value(data, "task_type")
    task_count = _int_value(data, "task_count")
    shared_library_repo_count = _int_value(data, "shared_library_repo_count")
    consumer_repo_mode = _string_value(data, "consumer_repo_mode")
    python_version_target = _string_value(data, "python_version_target")
    context_modes = _string_list_value(data, "context_modes")
    seed = _int_value(data, "seed")

    if not family_name:
        raise ValueError("Synthetic family config is missing family_name.")
    if not family_version:
        raise ValueError("Synthetic family config is missing family_version.")
    if task_type not in SUPPORTED_SYNTHETIC_TASK_TYPES:
        raise ValueError(f"Unsupported synthetic task type in config: {task_type!r}")
    if task_count < 1:
        raise ValueError("Synthetic family config task_count must be at least 1.")
    if shared_library_repo_count < 0:
        raise ValueError("shared_library_repo_count must be at least 0.")
    if not consumer_repo_mode:
        raise ValueError("Synthetic family config is missing consumer_repo_mode.")
    if not python_version_target:
        raise ValueError("Synthetic family config is missing python_version_target.")
    if not context_modes:
        raise ValueError("Synthetic family config must include at least one context mode.")

    return SyntheticGenerationConfig(
        family_name=family_name,
        family_version=family_version,
        task_type=task_type,
        task_count=task_count,
        shared_library_repo_count=shared_library_repo_count,
        consumer_repo_mode=consumer_repo_mode,
        python_version_target=python_version_target,
        context_modes=context_modes,
        seed=seed,
    )


def _validate_manifest_generation_config(
    manifest_data: Mapping[str, object],
    config: SyntheticGenerationConfig,
) -> None:
    expected_pairs: list[tuple[str, object]] = [
        ("task_type", config.task_type),
        ("task_count", config.task_count),
        ("shared_library_repo_count", config.shared_library_repo_count),
        ("consumer_repo_mode", config.consumer_repo_mode),
        ("python_version_target", config.python_version_target),
        ("context_modes", list(config.context_modes)),
        ("seed", config.seed),
    ]
    for key, expected_value in expected_pairs:
        actual_value = manifest_data.get(key)
        if actual_value != expected_value:
            raise ValueError(
                "Synthetic family config and manifest generation_config differ for "
                f"{key!r}: {actual_value!r} != {expected_value!r}"
            )


def _parse_task(family_dir: Path, data: object) -> SyntheticTask:
    if not isinstance(data, Mapping):
        raise ValueError("Synthetic task entries must be JSON objects.")
    typed_data = _as_mapping(data)

    task_id = _string_value(typed_data, "task_id")
    task_type = _string_value(typed_data, "task_type")
    title = _string_value(typed_data, "title")
    problem_statement = _string_value(typed_data, "problem_statement")
    repo_a_name = _string_value(typed_data, "repo_a_name")
    repo_b_name = _string_value(typed_data, "repo_b_name")
    repo_a_id = _int_value(typed_data, "repo_a_id")
    repo_b_id = _int_value(typed_data, "repo_b_id")
    branch = _string_value(typed_data, "branch", DEFAULT_SYNTHETIC_BRANCH) or DEFAULT_SYNTHETIC_BRANCH
    buggy_patch_path = family_dir / _string_value(typed_data, "buggy_patch_path")
    gold_patch_path = family_dir / _string_value(typed_data, "gold_patch_path")
    pytest_targets = _string_list_value(typed_data, "pytest_targets")
    expected_relevant_files = _string_list_value(typed_data, "expected_relevant_files")
    expected_relevant_symbols = _string_list_value(typed_data, "expected_relevant_symbols")
    context_modes_supported = _string_list_value(typed_data, "context_modes_supported")
    visible_api_names = _string_list_value(typed_data, "visible_api_names")
    test_context = _string_value(typed_data, "test_context")
    consumer_edit_files = _extract_patch_paths(buggy_patch_path)
    consumer_test_files_list: list[str] = []
    for target in pytest_targets:
        target_path = _pytest_target_path(target)
        if target_path is not None:
            consumer_test_files_list.append(target_path)
    consumer_test_files = tuple(consumer_test_files_list)

    if not task_id:
        raise ValueError("Synthetic task is missing task_id.")
    if task_type not in SUPPORTED_SYNTHETIC_TASK_TYPES:
        raise ValueError(f"Synthetic task {task_id!r} has unsupported task_type {task_type!r}.")
    if not title:
        raise ValueError(f"Synthetic task {task_id!r} is missing title.")
    if not problem_statement:
        raise ValueError(f"Synthetic task {task_id!r} is missing problem_statement.")
    if not repo_a_name:
        raise ValueError(f"Synthetic task {task_id!r} is missing repo_a_name.")
    if repo_a_id < 1:
        raise ValueError(f"Synthetic task {task_id!r} must use a positive synthetic repo_a_id.")
    if repo_b_name and repo_b_id < 1:
        raise ValueError(f"Synthetic task {task_id!r} has repo_b_name but invalid repo_b_id.")
    if not buggy_patch_path.is_file():
        raise FileNotFoundError(f"Buggy patch not found for {task_id!r}: {buggy_patch_path}")
    if not gold_patch_path.is_file():
        raise FileNotFoundError(f"Gold patch not found for {task_id!r}: {gold_patch_path}")
    if not pytest_targets:
        raise ValueError(f"Synthetic task {task_id!r} must declare at least one pytest target.")
    if not context_modes_supported:
        raise ValueError(f"Synthetic task {task_id!r} must declare supported context modes.")

    return SyntheticTask(
        task_id=task_id,
        task_type=task_type,
        title=title,
        problem_statement=problem_statement,
        repo_a_name=repo_a_name,
        repo_b_name=repo_b_name,
        repo_a_id=repo_a_id,
        repo_b_id=repo_b_id,
        branch=branch,
        buggy_patch_path=buggy_patch_path,
        gold_patch_path=gold_patch_path,
        pytest_targets=pytest_targets,
        expected_relevant_files=expected_relevant_files,
        expected_relevant_symbols=expected_relevant_symbols,
        context_modes_supported=context_modes_supported,
        visible_api_names=visible_api_names,
        test_context=test_context,
        consumer_edit_files=consumer_edit_files,
        consumer_test_files=consumer_test_files,
    )


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        return
    shutil.copytree(source, destination)


def _extract_patch_paths(patch_path: Path) -> tuple[str, ...]:
    paths: list[str] = []
    for line in patch_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("+++ b/"):
            continue
        path = line.removeprefix("+++ b/").strip()
        if path and path != "/dev/null" and path not in paths:
            paths.append(path)
    return tuple(paths)


def _pytest_target_path(target: str) -> str | None:
    path = target.split("::", 1)[0].strip()
    return path or None


def _initialize_git_repo(repo_path: Path) -> None:
    if (repo_path / ".git").exists():
        return
    _run_git(repo_path, "init")
    _run_git(repo_path, "checkout", "-b", DEFAULT_SYNTHETIC_BRANCH)
    _run_git(repo_path, "config", "user.email", "synthetic-benchmark@example.com")
    _run_git(repo_path, "config", "user.name", "Synthetic Benchmark")
    _run_git(repo_path, "add", ".")
    _run_git(repo_path, "commit", "-m", "Initial synthetic benchmark state")


def _apply_patch(repo_path: Path, patch_path: Path) -> None:
    _run_command(repo_path, "git", "apply", str(patch_path.resolve()))


def _run_git(repo_path: Path, *args: str) -> None:
    _run_command(repo_path, "git", *args)


def _run_command(repo_path: Path, *args: str) -> None:
    try:
        subprocess.run(
            list(args),
            cwd=repo_path,
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        stdout = exc.stdout.strip()
        details = stderr or stdout or str(exc)
        raise RuntimeError(f"Command failed in {repo_path}: {' '.join(args)}\n{details}") from exc


def _write_repo_registry(
    output_path: Path,
    tasks: tuple[SyntheticTask, ...],
    *,
    has_shared_repo: bool = True,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if has_shared_repo:
        shared_repo_name = _shared_repo_name(tasks)
        shared_repo_id = _shared_repo_id(tasks)
        branch = _shared_repo_branch(tasks)
        payload: dict[str, object] = {
            shared_repo_name: {
                "github_repo_id": shared_repo_id,
                "branch": branch,
            }
        }
    else:
        consumer_names = {task.repo_a_name.lower() for task in tasks}
        if len(consumer_names) != 1:
            raise ValueError("Synthetic v1 only supports one consumer repository name per workspace.")
        branch = _shared_repo_branch(tasks)
        repo_id = min(task.repo_a_id for task in tasks)
        payload = {
            next(iter(consumer_names)): {
                "github_repo_id": repo_id,
                "branch": branch,
            }
        }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_selection_manifest(
    *,
    selection_manifest_path: Path,
    validation_report_path: Path,
    family: SyntheticFamily,
    tasks: list[PreparedSyntheticTask],
    repo_b_path: Path | None,
    repo_registry_path: Path,
    seed: int,
) -> None:
    selection_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "family_name": family.config.family_name,
        "family_version": family.config.family_version,
        "generation_config": {
            "task_type": family.config.task_type,
            "task_count": len(tasks),
            "shared_library_repo_count": family.config.shared_library_repo_count,
            "consumer_repo_mode": family.config.consumer_repo_mode,
            "python_version_target": family.config.python_version_target,
            "context_modes": list(family.config.context_modes),
            "seed": seed,
        },
        "repo_b_path": str(repo_b_path.resolve()) if repo_b_path is not None else "",
        "repo_registry_path": str(repo_registry_path.resolve()),
        "validation_report_path": str(validation_report_path.resolve()),
        "tasks": [
            {
                "task_id": prepared.task.task_id,
                "task_type": prepared.task.task_type,
                "repo_a_path": str(prepared.repo_a_path.resolve()),
                "repo_a_name": prepared.task.repo_a_name,
                "repo_b_name": prepared.task.repo_b_name,
                "repo_a_id": prepared.task.repo_a_id,
                "repo_b_id": prepared.task.repo_b_id,
                "branch": prepared.task.branch,
                "pytest_targets": list(prepared.task.pytest_targets),
            }
            for prepared in tasks
        ],
    }
    selection_manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _indexed_repo_identity_for_workspace(
    workspace: PreparedSyntheticWorkspace,
) -> tuple[str, int, str]:
    """(full_name, github_repo_id, branch) for the repo we index for search/wiki/AST."""
    synth_tasks = tuple(prepared.task for prepared in workspace.tasks)
    branch = _shared_repo_branch(synth_tasks)
    if workspace.has_shared_repo:
        return (
            _shared_repo_name(synth_tasks),
            _shared_repo_id(synth_tasks),
            branch,
        )
    consumer_names = {task.repo_a_name.lower() for task in synth_tasks}
    if len(consumer_names) != 1:
        raise ValueError("Synthetic v1 only supports one consumer repository name per workspace.")
    repo_id = min(task.repo_a_id for task in synth_tasks)
    return next(iter(consumer_names)), repo_id, branch


def _shared_repo_name(tasks: tuple[SyntheticTask, ...]) -> str:
    repo_names = {task.repo_b_name.lower() for task in tasks}
    if len(repo_names) != 1:
        raise ValueError("Synthetic v1 only supports one shared library repository.")
    return next(iter(repo_names))


def _shared_repo_id(tasks: tuple[SyntheticTask, ...]) -> int:
    repo_ids = {task.repo_b_id for task in tasks}
    if len(repo_ids) != 1:
        raise ValueError("Synthetic v1 only supports one shared library repository id.")
    return next(iter(repo_ids))


def _shared_repo_branch(tasks: tuple[SyntheticTask, ...]) -> str:
    branches = {task.branch for task in tasks}
    if len(branches) != 1:
        raise ValueError("Synthetic v1 only supports one shared library branch.")
    return next(iter(branches))


def _ast_repo_id(base_repo_id: int) -> int:
    return base_repo_id + _AST_REPO_ID_OFFSET


def _ast_repo_name(base_repo_name: str) -> str:
    return f"{base_repo_name}{_AST_REPO_NAME_SUFFIX}"


def _string_value(data: Mapping[str, object], key: str, default: str = "") -> str:
    return str(data.get(key, default)).strip()


def _int_value(data: Mapping[str, object], key: str, default: int = 0) -> int:
    value = data.get(key, default)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return int(value)
    return default


def _string_list_value(data: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _as_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("Expected a mapping value.")
    return cast(Mapping[str, object], value)
