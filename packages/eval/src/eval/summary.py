from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from eval.harness import (
    DEFAULT_HARNESS_WORKDIR,
    HarnessEvaluationResult,
    resolve_evaluation_output_paths,
)


@dataclass(frozen=True)
class HarnessInstanceSummary:
    instance_id: str
    resolved: bool
    patch_exists: bool
    patch_successfully_applied: bool
    fail_to_pass_successes: tuple[str, ...]
    fail_to_pass_failures: tuple[str, ...]
    pass_to_pass_failures: tuple[str, ...]

    @property
    def status(self) -> str:
        if self.resolved:
            return "resolved"
        if not self.patch_exists:
            return "missing_patch"
        if not self.patch_successfully_applied:
            return "patch_failed"
        return "unresolved"


@dataclass(frozen=True)
class HarnessRunSummary:
    outputs: HarnessEvaluationResult
    total_instances: int
    submitted_instances: int
    completed_instances: int
    resolved_instances: int
    unresolved_instances: int
    empty_patch_instances: int
    error_instances: int
    instances: tuple[HarnessInstanceSummary, ...]


def summarize_swebench_run(
    *,
    predictions_path: Path,
    run_id: str,
    workdir: Path = DEFAULT_HARNESS_WORKDIR,
) -> HarnessRunSummary:
    outputs = resolve_evaluation_output_paths(
        predictions_path=predictions_path,
        run_id=run_id,
        workdir=workdir,
    )
    if not outputs.report_path.is_file():
        raise FileNotFoundError(f"Evaluation report not found: {outputs.report_path}")

    aggregate_data = _load_json_object(outputs.report_path)
    instances = _load_instance_summaries(outputs.run_log_dir)

    return HarnessRunSummary(
        outputs=outputs,
        total_instances=_int_field(aggregate_data, "total_instances"),
        submitted_instances=_int_field(aggregate_data, "submitted_instances"),
        completed_instances=_int_field(aggregate_data, "completed_instances"),
        resolved_instances=_int_field(aggregate_data, "resolved_instances"),
        unresolved_instances=_int_field(aggregate_data, "unresolved_instances"),
        empty_patch_instances=_int_field(aggregate_data, "empty_patch_instances"),
        error_instances=_int_field(aggregate_data, "error_instances"),
        instances=instances,
    )


def _load_instance_summaries(run_log_dir: Path) -> tuple[HarnessInstanceSummary, ...]:
    if not run_log_dir.exists():
        return tuple()

    summaries: list[HarnessInstanceSummary] = []
    for report_path in sorted(run_log_dir.glob("*/report.json")):
        report_data = _load_json_object(report_path)
        for instance_id, raw_summary in sorted(report_data.items()):
            if not isinstance(instance_id, str):
                continue
            typed_summary = _as_mapping(raw_summary)
            if typed_summary is None:
                continue
            tests_status = _mapping_field(typed_summary, "tests_status")
            summaries.append(
                HarnessInstanceSummary(
                    instance_id=instance_id,
                    resolved=_bool_field(typed_summary, "resolved"),
                    patch_exists=_bool_field(typed_summary, "patch_exists"),
                    patch_successfully_applied=_bool_field(
                        typed_summary, "patch_successfully_applied"
                    ),
                    fail_to_pass_successes=tuple(
                        _string_list_field(_mapping_field(tests_status, "FAIL_TO_PASS"), "success")
                    ),
                    fail_to_pass_failures=tuple(
                        _string_list_field(_mapping_field(tests_status, "FAIL_TO_PASS"), "failure")
                    ),
                    pass_to_pass_failures=tuple(
                        _string_list_field(_mapping_field(tests_status, "PASS_TO_PASS"), "failure")
                    ),
                )
            )

    summaries.sort(key=lambda summary: summary.instance_id)
    return tuple(summaries)


def _load_json_object(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return cast(dict[str, object], data)
    raise ValueError(f"Expected JSON object in {path}, found {type(data).__name__}")


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return None


def _mapping_field(data: Mapping[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    typed_value = _as_mapping(value)
    if typed_value is not None:
        return dict(typed_value)
    return {}


def _int_field(data: Mapping[str, object], key: str) -> int:
    value = data.get(key, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return 0


def _bool_field(data: Mapping[str, object], key: str) -> bool:
    value = data.get(key, False)
    if isinstance(value, bool):
        return value
    return False


def _string_list_field(data: Mapping[str, object], key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
