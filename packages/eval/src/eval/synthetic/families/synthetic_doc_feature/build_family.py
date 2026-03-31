from __future__ import annotations

import json
from pathlib import Path


FAMILY_DIR = Path(__file__).resolve().parent
TASKS_PATH = FAMILY_DIR / "tasks.json"
FAMILY_CONFIG_PATH = FAMILY_DIR / "family.json"
PATCHES_BUGGY = FAMILY_DIR / "patches" / "buggy"
PATCHES_GOLD = FAMILY_DIR / "patches" / "gold"

TASK_IDS = tuple(f"{i:03d}" for i in range(1, 31))


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
        expected_id = f"doc-feat-{suffix}"
        if expected_id not in seen_ids:
            errors.append(f"missing expected task: {expected_id}")

    return errors


def regenerate() -> None:
    """Re-read family.json and write a fresh tasks.json from existing task data."""
    family = json.loads(FAMILY_CONFIG_PATH.read_text(encoding="utf-8"))
    tasks_raw = json.loads(TASKS_PATH.read_text(encoding="utf-8"))

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
        "tasks": sorted(
            tasks_raw["tasks"],
            key=lambda t: int(str(t["task_id"]).split("-")[-1]),
        ),
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
