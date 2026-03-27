"""PyBugHive adapter — loads bugs from the PyBugHive benchmark.

PyBugHive contains 149 manually validated bugs from 11 Python projects.
Each bug includes a bug report summary, ground-truth patch, triggering
test cases, and environment setup commands.

Config options:
    source: path to local PyBugHive clone
    project: optional filter for a single project
    max_instances: cap the number of tasks loaded
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from lighthouse_eval.context.base import ContextProvider
from lighthouse_eval.datasets.adapters import register
from lighthouse_eval.datasets.adapters.base import RepoInfo, resolve_github_repo_id
from lighthouse_eval.datasets.schema import (
    Dataset,
    EvaluatorKind,
    OutputFormat,
    Task,
    TaskProvenance,
    TestSpec,
)
from lighthouse_eval.execution.preparation import (
    clone_git_repository,
    materialize_cached_workspace,
    require_executable,
)
from lighthouse_eval.execution.evaluators.test_execution import PytestEvaluator

log = logging.getLogger(__name__)

_TRANSFORM_VERSION = "1.0.0"
_PROJECT_TO_REPO = {
    "ansible": "ansible/ansible",
    "black": "psf/black",
    "cookiecutter": "cookiecutter/cookiecutter",
    "fastapi": "fastapi/fastapi",
    "keras": "keras-team/keras",
    "luigi": "spotify/luigi",
    "matplotlib": "matplotlib/matplotlib",
    "pandas": "pandas-dev/pandas",
    "sanic": "sanic-org/sanic",
    "scrapy": "scrapy/scrapy",
    "spacy": "explosion/spaCy",
    "tornado": "tornadoweb/tornado",
}


@register("pybughive")
class PyBugHiveAdapter:
    """Loads PyBugHive bugs into the canonical Task schema.

    Expects a local clone with the standard PyBugHive layout where each
    bug has a JSON metadata file describing the bug report, test commands,
    and patch.
    """

    name = "pybughive"
    transform_version = _TRANSFORM_VERSION

    def load(self, config: dict[str, Any]) -> Dataset:
        root = _require_pybughive_root(config)
        project_filter = config.get("project")
        max_instances = config.get("max_instances")

        tasks: list[Task] = []
        bugs_dir = root / "bugs"
        if not bugs_dir.is_dir():
            bugs_dir = root

        for bug_path in sorted(bugs_dir.rglob("*.json")):
            if max_instances and len(tasks) >= max_instances:
                break
            task = self._load_bug(bug_path, project_filter)
            if task is not None:
                tasks.append(task)

        log.info("Loaded %d PyBugHive tasks", len(tasks))
        return Dataset(name="pybughive", tasks=tasks)

    def _load_bug(self, bug_path: Path, project_filter: str | None) -> Task | None:
        try:
            data = json.loads(bug_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("Skipping unreadable bug file: %s", bug_path)
            return None

        project = data.get("project", bug_path.parent.name)
        if project_filter and project != project_filter:
            return None

        bug_id = data.get("bug_id", bug_path.stem)
        instance_id = f"{project}:{bug_id}"

        summary = data.get("bug_report", data.get("summary", ""))
        description = f"Fix bug #{bug_id} in {project}.\n\n{summary}"

        test_commands = data.get("test_commands", [])
        if isinstance(test_commands, str):
            test_commands = [test_commands]
        if not test_commands:
            test_commands = ["python -m pytest --tb=short -q"]

        setup_commands = data.get("setup_commands", [])
        if isinstance(setup_commands, str):
            setup_commands = [setup_commands]

        test_spec = TestSpec(
            execution_backend="command_sequence",
            test_commands=test_commands,
            setup_commands=[str(command) for command in setup_commands],
            timeout_seconds=data.get("timeout_seconds", 300),
            setup_timeout_seconds=data.get("setup_timeout_seconds"),
        )

        return Task(
            id=f"pybughive:{instance_id}",
            provenance=TaskProvenance(
                source_dataset="pybughive",
                source_instance_id=instance_id,
                transform_version=self.transform_version,
                comparability_class="pybughive:test_execution",
            ),
            evaluator_kind=EvaluatorKind.test_execution,
            output_format=OutputFormat.patch,
            description=description,
            target_files=data.get("target_files", []),
            test_spec=test_spec,
            metadata={
                "project": project,
                "bug_id": bug_id,
                "gold_patch": data.get("patch", ""),
                "repo_full_name": _infer_repo_full_name(data),
                "bug_file": str(bug_path),
                "benchmark_record": data,
            },
        )

    def get_evaluator(self):
        return PytestEvaluator()

    def get_oracle_provider(self) -> ContextProvider | None:
        return None

    def validate_runtime(
        self,
        config: dict[str, Any],
        dataset: Dataset,
        cache_root: Path,
    ) -> None:
        root = _require_pybughive_root(config)
        needs_git = False

        for task in dataset.tasks:
            if task.evaluator_kind != EvaluatorKind.test_execution:
                continue
            record = _benchmark_record(task)
            source_path = _resolve_pybughive_workspace_source(root, record)
            if source_path is not None:
                continue

            repo_url = _infer_repo_url(record)
            commit = _infer_commit(record)
            if not repo_url or not commit:
                raise RuntimeError(
                    f"PyBugHive task {task.id} does not provide a local workspace path "
                    "or enough repo/commit metadata to materialize one."
                )
            needs_git = True

        if needs_git:
            require_executable("git")

    def prepare_task_workspace(
        self,
        task: Task,
        config: dict[str, Any],
        cache_root: Path,
    ) -> Path:
        root = _require_pybughive_root(config)
        record = _benchmark_record(task)
        source_path = _resolve_pybughive_workspace_source(root, record)
        repo_url = _infer_repo_url(record)
        commit = _infer_commit(record)
        spec = task.test_spec

        if source_path is None and (not repo_url or not commit):
            raise RuntimeError(
                f"PyBugHive task {task.id} does not provide enough workspace metadata."
            )

        return materialize_cached_workspace(
            adapter_name=self.name,
            task=task,
            cache_root=cache_root,
            state={
                "benchmark_root": str(root.resolve()),
                "source_path": str(source_path.resolve()) if source_path else None,
                "repo_url": repo_url,
                "commit": commit,
            },
            build_fn=lambda build_dir: _build_pybughive_workspace(
                source_path=source_path,
                repo_url=repo_url,
                commit=commit,
                build_dir=build_dir,
            ),
            setup_commands=spec.setup_commands if spec else [],
            setup_timeout_seconds=spec.setup_timeout_seconds if spec else None,
        )

    def get_repos(self, config: dict[str, Any]) -> list[RepoInfo]:
        try:
            root = _require_pybughive_root(config)
        except (ValueError, FileNotFoundError):
            return []

        github_token = config.get("github_token")
        default_branches = config.get("branches", ["main"])
        seen: set[str] = set()
        repos: list[RepoInfo] = []

        bugs_dir = root / "bugs"
        if not bugs_dir.is_dir():
            bugs_dir = root

        for bug_path in sorted(bugs_dir.rglob("*.json")):
            try:
                data = json.loads(bug_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            full_name = _infer_repo_full_name(data)
            if not full_name or full_name in seen:
                continue
            seen.add(full_name)
            repos.append(
                RepoInfo(
                    github_repo_id=resolve_github_repo_id(full_name, github_token=github_token),
                    repo_url=f"https://github.com/{full_name}",
                    full_name=full_name,
                    branches=list(default_branches),
                )
            )

        return repos


def _infer_repo_full_name(data: dict[str, Any]) -> str | None:
    for key in ("repo", "repo_name", "github_repo", "full_name"):
        value = str(data.get(key, "")).strip()
        if "/" in value:
            return value
    project = str(data.get("project", "")).strip()
    if project in _PROJECT_TO_REPO:
        return _PROJECT_TO_REPO[project]
    return None


def _require_pybughive_root(config: dict[str, Any]) -> Path:
    source_path = config.get("source") or config.get("path")
    if source_path is None:
        raise ValueError(
            "PyBugHiveAdapter requires 'source' or 'path' pointing to a local PyBugHive clone."
        )
    root = Path(source_path)
    if not root.is_dir():
        raise FileNotFoundError(f"PyBugHive root not found: {root}")
    return root


def _benchmark_record(task: Task) -> dict[str, Any]:
    record = task.metadata.get("benchmark_record", {})
    return record if isinstance(record, dict) else {}


def _resolve_pybughive_workspace_source(root: Path, record: dict[str, Any]) -> Path | None:
    for key in ("workspace_path", "repo_path", "source_path", "buggy_path", "project_path"):
        value = str(record.get(key, "")).strip()
        if not value:
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.is_dir():
            return candidate
    return None


def _infer_commit(record: dict[str, Any]) -> str | None:
    for key in ("buggy_commit", "base_commit", "commit", "buggy_revision", "revision", "sha"):
        value = str(record.get(key, "")).strip()
        if value:
            return value
    return None


def _infer_repo_url(record: dict[str, Any]) -> str | None:
    for key in ("repo_url", "git_url", "clone_url"):
        value = str(record.get(key, "")).strip()
        if value:
            return value

    full_name = _infer_repo_full_name(record)
    if full_name:
        return f"https://github.com/{full_name}.git"
    return None


def _build_pybughive_workspace(
    *,
    source_path: Path | None,
    repo_url: str | None,
    commit: str | None,
    build_dir: Path,
) -> None:
    if source_path is not None:
        shutil.copytree(source_path, build_dir)
        return

    if not repo_url or not commit:
        raise RuntimeError("PyBugHive workspace preparation requires a source path or repo+commit.")

    clone_git_repository(repo_url, commit, build_dir)
