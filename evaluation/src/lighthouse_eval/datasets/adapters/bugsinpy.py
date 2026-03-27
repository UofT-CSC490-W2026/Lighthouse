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
import shlex
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
    materialize_cached_workspace,
    require_executable,
    run_process,
    run_shell_commands,
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
        root = _require_bugsinpy_root(config)
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

        bug_info = _parse_bug_info(bug_info_path)
        if bug_info_path.exists():
            description_parts.append(bug_info_path.read_text(encoding="utf-8", errors="replace"))

        if not run_test_path.exists():
            raise ValueError(
                f"BugsInPy bug {instance_id} is missing run_test.sh; cannot derive test commands."
            )

        test_command = run_test_path.read_text(encoding="utf-8", errors="replace").strip()
        if not test_command:
            raise ValueError(
                f"BugsInPy bug {instance_id} has an empty run_test.sh; cannot derive test commands."
            )

        test_spec = TestSpec(
            execution_backend="command_sequence",
            test_commands=[test_command],
            setup_commands=_load_setup_commands(bug_dir),
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
            metadata={
                "project": project,
                "bug_id": bug_id,
                "bug_info": bug_info,
                "bug_dir": str(bug_dir),
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
        root = _require_bugsinpy_root(config)
        if not (root / "projects").is_dir():
            raise RuntimeError(f"BugsInPy root does not contain projects/: {root}")

        template = str(config.get("checkout_command_template", "")).strip()
        if template:
            executable = shlex.split(template)[0]
            require_executable(executable)
            return

        materialized = all(
            _find_materialized_bugsinpy_workspace(root, task) is not None
            for task in dataset.tasks
            if task.evaluator_kind == EvaluatorKind.test_execution
        )
        if not materialized:
            require_executable("bugsinpy-checkout")

    def prepare_task_workspace(
        self,
        task: Task,
        config: dict[str, Any],
        cache_root: Path,
    ) -> Path:
        root = _require_bugsinpy_root(config)
        project = str(task.metadata.get("project", "")).strip()
        bug_id = str(task.metadata.get("bug_id", "")).strip()
        if not project or not bug_id:
            raise RuntimeError(f"BugsInPy task {task.id} is missing project/bug_id metadata.")

        spec = task.test_spec
        bug_info = task.metadata.get("bug_info", {})
        return materialize_cached_workspace(
            adapter_name=self.name,
            task=task,
            cache_root=cache_root,
            state={
                "benchmark_root": str(root.resolve()),
                "project": project,
                "bug_id": bug_id,
                "bug_info": bug_info,
                "checkout_command_template": config.get("checkout_command_template"),
            },
            build_fn=lambda build_dir: _build_bugsinpy_workspace(
                benchmark_root=root,
                task=task,
                build_dir=build_dir,
                checkout_command_template=str(config.get("checkout_command_template", "")).strip()
                or None,
            ),
            setup_commands=spec.setup_commands if spec else [],
            setup_timeout_seconds=spec.setup_timeout_seconds if spec else None,
        )

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


def _require_bugsinpy_root(config: dict[str, Any]) -> Path:
    source_path = config.get("source") or config.get("path")
    if source_path is None:
        raise ValueError(
            "BugsInPyAdapter requires 'source' or 'path' pointing to a local BugsInPy clone."
        )
    root = Path(source_path)
    if not root.is_dir():
        raise FileNotFoundError(f"BugsInPy root not found: {root}")
    return root


def _parse_bug_info(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def _load_setup_commands(bug_dir: Path) -> list[str]:
    commands: list[str] = []
    for filename in ("setup.sh", "install.sh"):
        path = bug_dir / filename
        if path.exists():
            command = path.read_text(encoding="utf-8", errors="replace").strip()
            if command:
                commands.append(command)
    return commands


def _find_materialized_bugsinpy_workspace(root: Path, task: Task) -> Path | None:
    project = str(task.metadata.get("project", "")).strip()
    bug_id = str(task.metadata.get("bug_id", "")).strip()
    if not project or not bug_id:
        return None

    candidates = [
        root / "projects" / project / "bugs" / bug_id / "workspace",
        root / "workspaces" / project / bug_id,
        root / "workspaces" / project / bug_id / "buggy",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _build_bugsinpy_workspace(
    *,
    benchmark_root: Path,
    task: Task,
    build_dir: Path,
    checkout_command_template: str | None,
) -> None:
    materialized = _find_materialized_bugsinpy_workspace(benchmark_root, task)
    if materialized is not None:
        shutil.copytree(materialized, build_dir)
        return

    project = str(task.metadata.get("project", "")).strip()
    bug_id = str(task.metadata.get("bug_id", "")).strip()
    if not project or not bug_id:
        raise RuntimeError(f"BugsInPy task {task.id} is missing project/bug_id metadata.")

    if checkout_command_template:
        command = checkout_command_template.format(
            project=project,
            bug_id=bug_id,
            workspace=str(build_dir),
            root=str(benchmark_root),
        )
        run_shell_commands([command], cwd=benchmark_root, timeout_seconds=600)
    else:
        run_process(
            [
                "bugsinpy-checkout",
                "-p",
                project,
                "-i",
                bug_id,
                "-v",
                "0",
                "-w",
                str(build_dir),
            ],
            cwd=benchmark_root,
            timeout_seconds=600,
        )

    if not build_dir.is_dir():
        raise RuntimeError(
            "BugsInPy workspace preparation did not create the expected workspace directory. "
            "If your checkout tool uses a different CLI shape, set dataset.options."
            "checkout_command_template."
        )
