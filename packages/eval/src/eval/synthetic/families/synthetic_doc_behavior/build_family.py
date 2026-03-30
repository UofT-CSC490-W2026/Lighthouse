from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


FAMILY_DIR = Path(__file__).resolve().parent
TASKS_PATH = FAMILY_DIR / "tasks.json"
FAMILY_CONFIG_PATH = FAMILY_DIR / "family.json"
PATCHES_BUGGY = FAMILY_DIR / "patches" / "buggy"
PATCHES_GOLD = FAMILY_DIR / "patches" / "gold"
REPO_A_TEMPLATE = FAMILY_DIR / "repo_a_template"
REPO_B_TEMPLATE = FAMILY_DIR / "repo_b_template"

TASK_IDS = tuple(f"{i:03d}" for i in range(1, 11))


def validate() -> list[str]:
    """Return a list of validation errors (empty means OK)."""
    errors: list[str] = []

    if not FAMILY_CONFIG_PATH.exists():
        errors.append("family.json not found")
        return errors

    family = json.loads(FAMILY_CONFIG_PATH.read_text(encoding="utf-8"))
    tasks_raw = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    tasks = tasks_raw.get("tasks", [])

    if len(tasks) != family["task_count"]:
        errors.append(
            f"task_count mismatch: family.json says {family['task_count']}, "
            f"tasks.json has {len(tasks)}"
        )

    seen_ids: set[str] = set()
    for task in tasks:
        tid = task["task_id"]
        if tid in seen_ids:
            errors.append(f"duplicate task_id: {tid}")
        seen_ids.add(tid)

        for key in ("buggy_patch_path", "gold_patch_path"):
            patch_path = FAMILY_DIR / task[key]
            if not patch_path.exists():
                errors.append(f"{tid}: missing {key} at {task[key]}")

        if task["task_type"] != family["task_type"]:
            errors.append(
                f"{tid}: task_type '{task['task_type']}' != family '{family['task_type']}'"
            )

    for suffix in TASK_IDS:
        expected_id = f"doc-behav-{suffix}"
        if expected_id not in seen_ids:
            errors.append(f"missing expected task: {expected_id}")

    return errors


def _sorted_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(tasks, key=lambda t: int(str(t["task_id"]).split("-")[-1]))


def _parse_buggy_patch_intent(*, patch_path: Path) -> tuple[str, list[tuple[str, str]]]:
    target_rel_path: str | None = None
    replacements: list[tuple[str, str]] = []
    old_hunk_lines: list[str] = []
    new_hunk_lines: list[str] = []
    hunk_has_change = False
    patch_lines = patch_path.read_text(encoding="utf-8").splitlines()

    def flush_replacement() -> None:
        nonlocal old_hunk_lines, new_hunk_lines, hunk_has_change
        if not old_hunk_lines and not new_hunk_lines:
            return
        if hunk_has_change:
            old_block = "\n".join(old_hunk_lines)
            new_block = "\n".join(new_hunk_lines)
            replacements.append((old_block, new_block))
        old_hunk_lines = []
        new_hunk_lines = []
        hunk_has_change = False

    for line in patch_lines:
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) < 4:
                raise ValueError(f"Malformed diff header in {patch_path}: {line!r}")
            a_path = parts[2]
            b_path = parts[3]
            if not a_path.startswith("a/") or not b_path.startswith("b/"):
                raise ValueError(f"Malformed git paths in {patch_path}: {line!r}")
            candidate_rel_path = a_path[2:]
            if target_rel_path is None:
                target_rel_path = candidate_rel_path
            elif target_rel_path != candidate_rel_path:
                raise ValueError(
                    f"{patch_path} touches multiple files; expected exactly one file."
                )
            continue
        if line.startswith("@@"):
            flush_replacement()
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        if line.startswith(" "):
            old_hunk_lines.append(line[1:])
            new_hunk_lines.append(line[1:])
            continue
        if line.startswith("-"):
            old_hunk_lines.append(line[1:])
            hunk_has_change = True
            continue
        if line.startswith("+"):
            new_hunk_lines.append(line[1:])
            hunk_has_change = True
            continue

    flush_replacement()
    if target_rel_path is None:
        raise ValueError(f"Could not determine patch target file for {patch_path}.")
    if not replacements:
        raise ValueError(f"No replacement hunks found in {patch_path}.")
    return target_rel_path, replacements


def _apply_replacements(*, source_text: str, replacements: list[tuple[str, str]], task_id: str) -> str:
    mutated = source_text
    for index, (old_block, new_block) in enumerate(replacements, start=1):
        if old_block not in mutated:
            raise ValueError(
                f"{task_id}: replacement block {index} does not match template content."
            )
        mutated = mutated.replace(old_block, new_block, 1)
    return mutated


def _render_git_patch(*, old_text: str, new_text: str, file_rel_path: str) -> str:
    diff_lines = list(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=f"a/{file_rel_path}",
            tofile=f"b/{file_rel_path}",
            lineterm="",
            n=3,
        )
    )
    if not diff_lines:
        raise ValueError(f"No diff produced for {file_rel_path}.")
    return (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        + "\n".join(diff_lines)
        + "\n"
    )


def _run_checked(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or "(no command output)"
        joined = " ".join(command)
        raise RuntimeError(f"Command failed [{joined}]: {detail}")


def _validate_patch_pair(*, buggy_patch_path: Path, gold_patch_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="doc-behav-patch-") as temp_dir:
        temp_root = Path(temp_dir)
        temp_repo = temp_root / "repo"
        shutil.copytree(REPO_A_TEMPLATE, temp_repo)
        _run_checked(["git", "-C", str(temp_repo), "apply", "--check", str(buggy_patch_path)])
        _run_checked(["git", "-C", str(temp_repo), "apply", str(buggy_patch_path)])
        _run_checked(["git", "-C", str(temp_repo), "apply", "--check", str(gold_patch_path)])


def _run_pytest_for_task(*, repo_a_path: Path, repo_b_path: Path, pytest_targets: list[str]) -> int:
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    extra_paths = f"{repo_a_path.resolve()}:{repo_b_path.resolve()}"
    env["PYTHONPATH"] = (
        f"{extra_paths}:{existing_pythonpath}" if existing_pythonpath else extra_paths
    )
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *pytest_targets],
        cwd=repo_a_path,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return completed.returncode


def _validate_mutant_behavior(
    *,
    task_id: str,
    pytest_targets: list[str],
    buggy_patch_path: Path,
    gold_patch_path: Path,
) -> None:
    with tempfile.TemporaryDirectory(prefix="doc-behav-semantic-") as temp_dir:
        temp_root = Path(temp_dir)
        repo_a_path = temp_root / "repo_a"
        repo_b_path = temp_root / "repo_b"
        shutil.copytree(REPO_A_TEMPLATE, repo_a_path)
        shutil.copytree(REPO_B_TEMPLATE, repo_b_path)
        _run_checked(["git", "-C", str(repo_a_path), "apply", str(buggy_patch_path)])
        buggy_returncode = _run_pytest_for_task(
            repo_a_path=repo_a_path,
            repo_b_path=repo_b_path,
            pytest_targets=pytest_targets,
        )
        if buggy_returncode == 0:
            raise RuntimeError(
                f"{task_id}: buggy mutant still passes pytest targets {pytest_targets}"
            )
        _run_checked(["git", "-C", str(repo_a_path), "apply", str(gold_patch_path)])
        repaired_returncode = _run_pytest_for_task(
            repo_a_path=repo_a_path,
            repo_b_path=repo_b_path,
            pytest_targets=pytest_targets,
        )
        if repaired_returncode != 0:
            raise RuntimeError(
                f"{task_id}: gold patch does not repair pytest targets {pytest_targets}"
            )


def canonicalize_patches() -> None:
    tasks_raw = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    tasks = tasks_raw.get("tasks", [])
    for task in _sorted_tasks(tasks):
        task_id = str(task["task_id"])
        buggy_patch_path = FAMILY_DIR / str(task["buggy_patch_path"])
        gold_patch_path = FAMILY_DIR / str(task["gold_patch_path"])
        file_rel_path, replacements = _parse_buggy_patch_intent(patch_path=buggy_patch_path)
        template_file = REPO_A_TEMPLATE / file_rel_path
        base_text = template_file.read_text(encoding="utf-8")
        buggy_text = _apply_replacements(
            source_text=base_text,
            replacements=replacements,
            task_id=task_id,
        )
        buggy_patch = _render_git_patch(
            old_text=base_text,
            new_text=buggy_text,
            file_rel_path=file_rel_path,
        )
        gold_patch = _render_git_patch(
            old_text=buggy_text,
            new_text=base_text,
            file_rel_path=file_rel_path,
        )
        buggy_patch_path.write_text(buggy_patch, encoding="utf-8")
        gold_patch_path.write_text(gold_patch, encoding="utf-8")
        _validate_patch_pair(
            buggy_patch_path=buggy_patch_path,
            gold_patch_path=gold_patch_path,
        )
        _validate_mutant_behavior(
            task_id=task_id,
            pytest_targets=list(task["pytest_targets"]),
            buggy_patch_path=buggy_patch_path,
            gold_patch_path=gold_patch_path,
        )


def regenerate() -> None:
    """Rewrite patch files in canonical format and refresh tasks.json."""
    family = json.loads(FAMILY_CONFIG_PATH.read_text(encoding="utf-8"))
    tasks_raw = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    canonicalize_patches()

    payload = {
        "family_name": family["family_name"],
        "family_version": family["family_version"],
        "generation_config": {
            "task_type": family["task_type"],
            "task_count": family["task_count"],
            "shared_library_repo_count": family["shared_library_repo_count"],
            "consumer_repo_mode": family["consumer_repo_mode"],
            "python_version_target": family["python_version_target"],
            "context_modes": family["context_modes"],
            "seed": family["seed"],
        },
        "tasks": _sorted_tasks(tasks_raw["tasks"]),
    }
    TASKS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    errors = validate()
    if errors:
        print("Validation errors:")
        for err in errors:
            print(f"  - {err}")
        raise SystemExit(1)

    regenerate()
    print(f"Regenerated {TASKS_PATH.name} with {len(TASK_IDS)} tasks.")


if __name__ == "__main__":
    main()
