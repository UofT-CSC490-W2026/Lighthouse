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
        source_path = config.get("source") or config.get("path")
        if source_path is None:
            raise ValueError(
                "PyBugHiveAdapter requires 'source' or 'path' pointing to a "
                "local PyBugHive clone."
            )
        root = Path(source_path)
        if not root.is_dir():
            raise FileNotFoundError(f"PyBugHive root not found: {root}")

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

        test_spec = TestSpec(
            execution_backend="command_sequence",
            test_commands=test_commands,
            timeout_seconds=data.get("timeout_seconds", 300),
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
                "setup_commands": data.get("setup_commands", []),
            },
        )

    def get_evaluator(self):
        return PytestEvaluator()

    def get_oracle_provider(self) -> ContextProvider | None:
        return None

    def get_repos(self, config: dict[str, Any]) -> list[RepoInfo]:
        source_path = config.get("source") or config.get("path")
        if source_path is None:
            return []
        root = Path(source_path)
        if not root.is_dir():
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
