from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast


DEFAULT_DATASET_NAME = "princeton-nlp/SWE-bench_Lite"
DEFAULT_SPLIT = "test"
DatasetRow = Mapping[str, object]


@dataclass(frozen=True)
class SWEBenchTask:
    instance_id: str
    repo: str
    base_commit: str
    version: str
    problem_statement: str


def load_swebench_slice(
    *,
    dataset_name: str = DEFAULT_DATASET_NAME,
    split: str = DEFAULT_SPLIT,
    max_instances: int | None = None,
    instance_ids: list[str] | None = None,
) -> list[SWEBenchTask]:
    from datasets import load_dataset

    requested_ids = [value.strip() for value in (instance_ids or []) if value.strip()]
    dataset = load_dataset(dataset_name, split=split)

    if requested_ids:
        rows_by_id: dict[str, DatasetRow] = {}
        for row in dataset:
            typed_row = _as_dataset_row(row)
            if typed_row is None:
                continue
            instance_id = _string_field(typed_row, "instance_id")
            if instance_id:
                rows_by_id[instance_id] = typed_row

        missing = [instance_id for instance_id in requested_ids if instance_id not in rows_by_id]
        if missing:
            missing_display = ", ".join(missing)
            raise ValueError(f"Unknown SWE-bench instance id(s): {missing_display}")

        return [_row_to_task(rows_by_id[instance_id]) for instance_id in requested_ids]

    tasks: list[SWEBenchTask] = []
    for row in dataset:
        typed_row = _as_dataset_row(row)
        if typed_row is None:
            continue
        tasks.append(_row_to_task(typed_row))
        if max_instances is not None and len(tasks) >= max_instances:
            break
    return tasks


def _row_to_task(row: DatasetRow) -> SWEBenchTask:
    return SWEBenchTask(
        instance_id=_string_field(row, "instance_id"),
        repo=_string_field(row, "repo"),
        base_commit=_string_field(row, "base_commit"),
        version=_string_field(row, "version"),
        problem_statement=_string_field(row, "problem_statement"),
    )


def _as_dataset_row(row: object) -> DatasetRow | None:
    if isinstance(row, Mapping):
        return cast(DatasetRow, row)
    return None


def _string_field(row: DatasetRow, key: str) -> str:
    value = row.get(key, "")
    return str(value).strip()
