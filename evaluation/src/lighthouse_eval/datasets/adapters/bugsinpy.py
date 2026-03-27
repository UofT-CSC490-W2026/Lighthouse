"""BugsInPy adapter — loads bugs from the BugsInPy benchmark.

BugsInPy contains 493 real bugs from 17 Python projects with triggering
test cases.  The adapter shells out to ``bugsinpy-checkout`` (or reads
a pre-materialized checkout directory) to obtain buggy source and test
commands.

Config options:
    source: path to local BugsInPy clone (or "soarsmu/BugsInPy" for auto-clone)
    project: optional filter for a single project (e.g. "pandas")
    max_instances: cap the number of tasks loaded
"""

from __future__ import annotations

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
_PROJECTS = [
    "ansible", "black", "cookiecutter", "fastapi", "httpie",
    "keras", "luigi", "matplotlib", "pandas", "PySnooper",
    "sanic", "scrapy", "spacy", "thefuck", "tornado",
    "tqdm", "youtube-dl",
]
_PROJECT_TO_REPO = {
    "ansible": "ansible/ansible",
    "black": "psf/black",
    "cookiecutter": "cookiecutter/cookiecutter",
    "fastapi": "fastapi/fastapi",
    "httpie": "httpie/cli",
    "keras": "keras-team/keras",
    "luigi": "spotify/luigi",
    "matplotlib": "matplotlib/matplotlib",
    "pandas": "pandas-dev/pandas",
    "PySnooper": "cool-RR/PySnooper",
    "sanic": "sanic-org/sanic",
    "scrapy": "scrapy/scrapy",
    "spacy": "explosion/spaCy",
    "thefuck": "nvbn/thefuck",
    "tornado": "tornadoweb/tornado",
    "tqdm": "tqdm/tqdm",
    "youtube-dl": "ytdl-org/youtube-dl",
}


@register("bugsinpy")
class BugsInPyAdapter:
    """Loads BugsInPy bugs into the canonical Task schema.

    Expects either a local clone of the BugsInPy repository (with the
    standard ``projects/<name>/bugs/<id>/`` layout) or will attempt to
    discover bugs from the ``projects/`` subdirectory tree.
    """

    name = "bugsinpy"
    transform_version = _TRANSFORM_VERSION

    def load(self, config: dict[str, Any]) -> Dataset:
        source_path = config.get("source") or config.get("path")
        if source_path is None:
            raise ValueError(
                "BugsInPyAdapter requires 'source' or 'path' pointing to a "
                "local BugsInPy clone."
            )
        root = Path(source_path)
        if not root.is_dir():
            raise FileNotFoundError(f"BugsInPy root not found: {root}")

        project_filter = config.get("project")
        max_instances = config.get("max_instances")
        projects = [project_filter] if project_filter else _PROJECTS

        tasks: list[Task] = []
        for project in projects:
            project_dir = root / "projects" / project
            if not project_dir.is_dir():
                continue
            bugs_dir = project_dir / "bugs"
            if not bugs_dir.is_dir():
                continue
            for bug_dir in sorted(bugs_dir.iterdir()):
                if not bug_dir.is_dir():
                    continue
                if max_instances and len(tasks) >= max_instances:
                    break
                task = self._load_bug(project, bug_dir)
                if task is not None:
                    tasks.append(task)
            if max_instances and len(tasks) >= max_instances:
                break

        log.info("Loaded %d BugsInPy tasks", len(tasks))
        return Dataset(name="bugsinpy", tasks=tasks)

    def _load_bug(self, project: str, bug_dir: Path) -> Task | None:
        bug_id = bug_dir.name
        instance_id = f"{project}:{bug_id}"

        bug_info_path = bug_dir / "bug.info"
        run_test_path = bug_dir / "run_test.sh"

        description_parts = [f"Fix bug #{bug_id} in {project}."]

        if bug_info_path.exists():
            description_parts.append(bug_info_path.read_text(encoding="utf-8", errors="replace"))

        test_commands = ["bugsinpy-test"]
        if run_test_path.exists():
            test_commands = [run_test_path.read_text(encoding="utf-8", errors="replace").strip()]

        test_spec = TestSpec(
            execution_backend="command_sequence",
            test_commands=test_commands,
            docker_image=f"bugsinpy:{project}_{bug_id}",
            timeout_seconds=300,
        )

        return Task(
            id=f"bugsinpy:{instance_id}",
            provenance=TaskProvenance(
                source_dataset="bugsinpy",
                source_instance_id=instance_id,
                transform_version=self.transform_version,
                comparability_class="bugsinpy:test_execution",
            ),
            evaluator_kind=EvaluatorKind.test_execution,
            output_format=OutputFormat.patch,
            description="\n\n".join(description_parts),
            target_files=[],
            test_spec=test_spec,
            metadata={"project": project, "bug_id": bug_id},
        )

    def get_evaluator(self):
        return PytestEvaluator()

    def get_oracle_provider(self) -> ContextProvider | None:
        return None

    def get_repos(self, config: dict[str, Any]) -> list[RepoInfo]:
        project_filter = config.get("project")
        github_token = config.get("github_token")
        default_branches = config.get("branches", ["main"])
        projects = [project_filter] if project_filter else _PROJECTS

        repos: list[RepoInfo] = []
        for project in projects:
            full_name = _PROJECT_TO_REPO.get(project)
            if not full_name:
                log.warning("No GitHub mapping configured for BugsInPy project %s", project)
                continue
            repos.append(
                RepoInfo(
                    github_repo_id=resolve_github_repo_id(full_name, github_token=github_token),
                    repo_url=f"https://github.com/{full_name}",
                    full_name=full_name,
                    branches=list(default_branches),
                )
            )
        return repos
