from __future__ import annotations

import json
from pathlib import Path


FAMILY_DIR = Path(__file__).resolve().parent
TASKS_PATH = FAMILY_DIR / "tasks.json"
FAMILY_CONFIG_PATH = FAMILY_DIR / "family.json"
PATCHES_DIR = FAMILY_DIR / "patches"

TASK_IDS = tuple(f"{index:03d}" for index in range(1, 31))


def main() -> None:
    family_config = json.loads(FAMILY_CONFIG_PATH.read_text(encoding="utf-8"))
    raw = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    tasks = raw.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("Expected a tasks list in tasks.json")

    _validate_tasks(tasks)
    _validate_patches(tasks)

    payload = {
        "family_name": family_config["family_name"],
        "family_version": family_config["family_version"],
        "generation_config": {
            "task_type": family_config["task_type"],
            "task_count": family_config["task_count"],
            "shared_library_repo_count": family_config["shared_library_repo_count"],
            "consumer_repo_mode": family_config["consumer_repo_mode"],
            "python_version_target": family_config["python_version_target"],
            "context_modes": family_config["context_modes"],
            "seed": family_config["seed"],
        },
        "tasks": tasks,
    }
    TASKS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(tasks)} tasks to {TASKS_PATH}")


def _validate_tasks(tasks: list[dict[str, object]]) -> None:
    seen_ids: set[str] = set()
    for task in tasks:
        task_id = str(task.get("task_id", ""))
        suffix = task_id.split("-")[-1]
        if suffix not in TASK_IDS:
            raise ValueError(f"Unexpected task id suffix: {suffix}")
        if task_id in seen_ids:
            raise ValueError(f"Duplicate task id: {task_id}")
        seen_ids.add(task_id)

    missing = [tid for tid in TASK_IDS if f"wrong-op-{tid}" not in seen_ids]
    if missing:
        raise ValueError(f"Missing tasks: {', '.join(missing)}")


def _validate_patches(tasks: list[dict[str, object]]) -> None:
    for task in tasks:
        for key in ("buggy_patch_path", "gold_patch_path"):
            rel_path = str(task.get(key, ""))
            full_path = FAMILY_DIR / rel_path
            if not full_path.is_file():
                raise FileNotFoundError(
                    f"Patch file missing for {task.get('task_id')}: {full_path}"
                )


if __name__ == "__main__":
    main()
