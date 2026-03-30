from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


FAMILIES_ROOT = Path(__file__).resolve().parent


def _family_dirs() -> list[Path]:
    families: list[Path] = []
    for child in sorted(FAMILIES_ROOT.iterdir()):
        if not child.is_dir():
            continue
        if (child / "tasks.json").is_file() and (child / "repo_a_template").is_dir():
            families.append(child)
    return families


def _run_checked(command: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout).strip() or "(no output)"
        joined = " ".join(command)
        raise RuntimeError(f"Command failed in {cwd}: {joined}\n{details}")


def _validate_family_semantics(family_dir: Path) -> None:
    tasks_payload = json.loads((family_dir / "tasks.json").read_text(encoding="utf-8"))
    tasks = tasks_payload.get("tasks", [])
    if not isinstance(tasks, list) or not tasks:
        raise ValueError(f"Invalid or empty tasks list for {family_dir.name}")

    repo_a_template = family_dir / "repo_a_template"
    repo_b_template = family_dir / "repo_b_template" if (family_dir / "repo_b_template").is_dir() else None

    for task in tasks:
        task_id = str(task["task_id"])
        buggy_patch = (family_dir / str(task["buggy_patch_path"])).resolve()
        gold_patch = (family_dir / str(task["gold_patch_path"])).resolve()
        pytest_targets = list(task["pytest_targets"])
        if not pytest_targets:
            raise ValueError(f"{family_dir.name}:{task_id} has empty pytest_targets")

        with tempfile.TemporaryDirectory(prefix=f"{family_dir.name}-{task_id}-") as temp_dir:
            temp_root = Path(temp_dir)
            repo_a_path = temp_root / "repo_a"
            shutil.copytree(repo_a_template, repo_a_path)
            repo_b_path: Path | None = None
            if repo_b_template is not None:
                repo_b_path = temp_root / "repo_b"
                shutil.copytree(repo_b_template, repo_b_path)

            env = dict(os.environ)
            pythonpath_parts = [str(repo_a_path.resolve())]
            if repo_b_path is not None:
                pythonpath_parts.append(str(repo_b_path.resolve()))
            existing_pythonpath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = (
                ":".join(pythonpath_parts)
                + (":" + existing_pythonpath if existing_pythonpath else "")
            )
            env["PYTHONDONTWRITEBYTECODE"] = "1"

            _run_checked(["git", "apply", "--check", str(buggy_patch)], cwd=repo_a_path)
            _run_checked(["git", "apply", str(buggy_patch)], cwd=repo_a_path)

            buggy_run = subprocess.run(
                [sys.executable, "-B", "-m", "pytest", "-q", *pytest_targets],
                cwd=repo_a_path,
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            if buggy_run.returncode == 0:
                raise RuntimeError(
                    f"{family_dir.name}:{task_id} invalid: buggy state already passes tests "
                    f"{pytest_targets}"
                )

            _run_checked(["git", "apply", "--check", str(gold_patch)], cwd=repo_a_path)
            _run_checked(["git", "apply", str(gold_patch)], cwd=repo_a_path)

            repaired_run = subprocess.run(
                [sys.executable, "-B", "-m", "pytest", "-q", *pytest_targets],
                cwd=repo_a_path,
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            if repaired_run.returncode != 0:
                tail = "\n".join(repaired_run.stdout.splitlines()[-8:]).strip()
                raise RuntimeError(
                    f"{family_dir.name}:{task_id} invalid: gold state still fails tests "
                    f"{pytest_targets}\n{tail}"
                )


def main() -> None:
    families = _family_dirs()
    if not families:
        raise RuntimeError("No synthetic families found.")

    for family_dir in families:
        build_script = family_dir / "build_family.py"
        if build_script.is_file():
            print(f"[regen] {family_dir.name}")
            _run_checked([sys.executable, str(build_script)], cwd=FAMILIES_ROOT)
        print(f"[validate] {family_dir.name}")
        _validate_family_semantics(family_dir)

    print("All synthetic families regenerated and semantically validated.")


if __name__ == "__main__":
    main()
