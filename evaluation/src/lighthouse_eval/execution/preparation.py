from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from lighthouse_eval.candidates.base import UnifiedPatch
from lighthouse_eval.config import EvalConfig
from lighthouse_eval.datasets.schema import Dataset, EvaluatorKind, Task

log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def require_executable(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"Required executable {name!r} was not found on PATH.")
    return path


def run_process(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout_seconds: int | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Command failed: "
            f"{' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def run_shell_commands(
    commands: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
) -> None:
    for command in commands:
        stripped = command.strip()
        if not stripped:
            continue
        result = subprocess.run(
            stripped,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Shell command failed: "
                f"{stripped}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )


def clone_git_repository(repo_url: str, commit: str, destination: Path) -> None:
    run_process(["git", "clone", repo_url, str(destination)])
    run_process(["git", "checkout", "--detach", commit], cwd=destination)


def apply_patch_to_workspace(diff: str, workspace: Path) -> None:
    UnifiedPatch(diff=diff).apply(workspace)


def materialize_cached_workspace(
    *,
    adapter_name: str,
    task: Task,
    cache_root: Path,
    state: dict[str, Any],
    build_fn: Callable[[Path], None],
    setup_commands: list[str] | None = None,
    setup_timeout_seconds: int | None = None,
) -> Path:
    entry_dir = _cache_entry_dir(cache_root, adapter_name, task)
    workspace_dir = entry_dir / "workspace"
    manifest_path = entry_dir / "manifest.json"
    ready_path = entry_dir / ".prepared"

    cache_key = _cache_key(
        task=task,
        state=state,
        setup_commands=setup_commands or [],
        setup_timeout_seconds=setup_timeout_seconds,
    )

    if workspace_dir.is_dir() and ready_path.exists() and manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
        if manifest.get("cache_key") == cache_key:
            return workspace_dir

    if entry_dir.exists():
        shutil.rmtree(entry_dir)
    entry_dir.mkdir(parents=True, exist_ok=True)

    build_dir = entry_dir / ".build"
    try:
        build_fn(build_dir)
        if not build_dir.is_dir():
            raise RuntimeError(
                f"Workspace builder for task {task.id} did not create {build_dir}."
            )

        commands = [cmd for cmd in (setup_commands or []) if cmd.strip()]
        if commands:
            timeout = (
                setup_timeout_seconds
                or (task.test_spec.timeout_seconds if task.test_spec else 300)
            )
            run_shell_commands(
                commands,
                cwd=build_dir,
                timeout_seconds=timeout,
            )

        build_dir.rename(workspace_dir)
        manifest = {
            "cache_key": cache_key,
            "task_id": task.id,
            "adapter": adapter_name,
            "state": state,
            "setup_commands": commands,
            "setup_timeout_seconds": setup_timeout_seconds,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        ready_path.write_text(cache_key, encoding="utf-8")
        return workspace_dir
    except Exception:
        shutil.rmtree(entry_dir, ignore_errors=True)
        raise


def prepare_dataset_for_run(
    config: EvalConfig,
    dataset: Dataset,
    *,
    adapter=None,
    adapter_config: dict[str, Any] | None = None,
) -> None:
    test_tasks = [
        task for task in dataset.tasks if task.evaluator_kind == EvaluatorKind.test_execution
    ]
    if not test_tasks:
        return

    cache_root = config.workspace_cache_dir
    cache_root.mkdir(parents=True, exist_ok=True)
    runtime_adapter = adapter if _supports_runtime_preparation(adapter) else None
    normalized_adapter_config = adapter_config or {}
    adapter_name = getattr(adapter, "name", "dataset")

    if runtime_adapter is not None:
        runtime_adapter.validate_runtime(normalized_adapter_config, dataset, cache_root)

    for index, task in enumerate(test_tasks, start=1):
        if runtime_adapter is None and _is_cached_workspace(task.workspace_path, cache_root):
            continue

        if runtime_adapter is not None:
            workspace = runtime_adapter.prepare_task_workspace(
                task,
                normalized_adapter_config,
                cache_root,
            )
        elif task.workspace_path is not None:
            workspace = _prepare_existing_workspace(
                adapter_name=adapter_name,
                task=task,
                cache_root=cache_root,
            )
        else:
            raise RuntimeError(
                f"Task {task.id} requires a prepared workspace, but adapter "
                f"{adapter_name!r} does not implement runtime preparation."
            )

        task.workspace_path = workspace
        log.info(
            "Prepared workspace %d/%d for %s at %s",
            index,
            len(test_tasks),
            task.id,
            workspace,
        )


def _prepare_existing_workspace(
    *,
    adapter_name: str,
    task: Task,
    cache_root: Path,
) -> Path:
    source_workspace = task.workspace_path
    if source_workspace is None or not source_workspace.is_dir():
        raise RuntimeError(f"Task {task.id} has no usable workspace_path to prepare.")

    spec = task.test_spec
    state = {
        "source_workspace": str(source_workspace.resolve()),
        "source_mtime_ns": source_workspace.stat().st_mtime_ns,
    }
    return materialize_cached_workspace(
        adapter_name=adapter_name,
        task=task,
        cache_root=cache_root,
        state=state,
        build_fn=lambda build_dir: shutil.copytree(source_workspace, build_dir),
        setup_commands=spec.setup_commands if spec else [],
        setup_timeout_seconds=spec.setup_timeout_seconds if spec else None,
    )


def _cache_entry_dir(cache_root: Path, adapter_name: str, task: Task) -> Path:
    task_id = _SLUG_RE.sub("_", task.id).strip("._") or "task"
    digest = hashlib.sha256(task.id.encode("utf-8")).hexdigest()[:12]
    return cache_root / adapter_name / f"{task_id}_{digest}"


def _cache_key(
    *,
    task: Task,
    state: dict[str, Any],
    setup_commands: list[str],
    setup_timeout_seconds: int | None,
) -> str:
    payload = {
        "task_id": task.id,
        "provenance": task.provenance.model_dump(mode="json"),
        "test_spec": task.test_spec.model_dump(mode="json") if task.test_spec else None,
        "state": state,
        "setup_commands": setup_commands,
        "setup_timeout_seconds": setup_timeout_seconds,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _supports_runtime_preparation(adapter: object) -> bool:
    return callable(getattr(adapter, "validate_runtime", None)) and callable(
        getattr(adapter, "prepare_task_workspace", None)
    )


def _is_cached_workspace(path: Path | None, cache_root: Path) -> bool:
    if path is None or not path.is_dir():
        return False
    try:
        path.resolve().relative_to(cache_root.resolve())
    except ValueError:
        return False
    return True
