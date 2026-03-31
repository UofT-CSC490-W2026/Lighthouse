from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any

from eval.historical_runs import (
    has_full_repeat_coverage,
    list_completed_lighthouse_summaries,
    load_run_id_list,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PENDING_PATH = REPO_ROOT / "eval" / "configs" / "pending_configs.txt"
FAMILIES_ROOT = REPO_ROOT / "packages" / "eval" / "src" / "eval" / "synthetic" / "families"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / ".cache" / "eval" / "synthetic_experiments" / "queued" / "matrix"
DEFAULT_WORKSPACE_ROOT = REPO_ROOT / ".cache" / "eval" / "synthetic_workspace" / "queued"
DEFAULT_PREDICTIONS_ROOT = REPO_ROOT / ".cache" / "eval" / "synthetic_predictions" / "queued"
DEFAULT_RUNS_ROOT = REPO_ROOT / ".cache" / "eval" / "synthetic_runs" / "queued"
DEFAULT_ARTIFACTS_ROOT = REPO_ROOT / ".cache" / "eval" / "synthetic_experiments" / "queued"

REQUIRED_ROW_NUMERIC_FIELDS = (
    "mean_score_pct",
    "stddev_score_pct",
    "mean_total_duration_seconds",
    "mean_generation_total_tokens",
)
REQUIRED_ROW_NUMERIC_LIST_FIELDS = (
    "repeat_scores_pct",
    "repeat_total_duration_seconds",
    "repeat_generation_total_tokens",
)
OPTIONAL_COST_FIELDS = (
    "mean_generation_cost_usd",
    "repeat_generation_cost_usd",
)


def _slug(value: str) -> str:
    output = []
    for char in value.lower():
        if char.isalnum():
            output.append(char)
        else:
            output.append("-")
    slug = "".join(output).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "x"


def _short_run_prefix(config_path: Path) -> str:
    rel = str(config_path.relative_to(REPO_ROOT))
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]
    return f"queued-{digest}"


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _read_config(config_path: Path) -> dict[str, Any]:
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Config must be a JSON object: {config_path}")
    return raw


def _available_task_count_by_family() -> dict[str, int]:
    mapping: dict[str, int] = {}
    for child in sorted(FAMILIES_ROOT.iterdir()):
        family_path = child / "family.json"
        if not family_path.is_file():
            continue
        raw = json.loads(family_path.read_text(encoding="utf-8"))
        mapping[str(raw["family_name"])] = int(raw["task_count"])
    if not mapping:
        raise RuntimeError(f"No family metadata found under {FAMILIES_ROOT}")
    return mapping


def _validate_config_bounds(config: dict[str, Any], config_path: Path) -> None:
    families = config.get("families")
    if not isinstance(families, list) or len(families) != 1:
        raise ValueError(f"Config must contain singleton families list: {config_path}")
    family_name = str(families[0])
    requested_task_count = int(config["task_count"])
    available_map = _available_task_count_by_family()
    available = available_map.get(family_name)
    if available is None:
        raise ValueError(f"Unknown family in config: {family_name}")
    if requested_task_count > available:
        raise ValueError(
            f"Config task_count={requested_task_count} exceeds available={available} "
            f"for {family_name}. Regenerate configs with eval/configs/generate_configs.py."
        )


def _next_pending_config(pending_path: Path) -> Path:
    lines = pending_path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        value = line.strip()
        if value:
            return REPO_ROOT / value
    raise RuntimeError(f"No pending configs in {pending_path}")


def _remove_config_from_pending(pending_path: Path, config_path: Path) -> None:
    target = str(config_path.relative_to(REPO_ROOT))
    lines = pending_path.read_text(encoding="utf-8").splitlines()
    remaining: list[str] = []
    removed = False
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if not removed and line == target:
            removed = True
            continue
        remaining.append(line)
    if not removed:
        raise RuntimeError(f"Config not found in pending queue: {target}")
    pending_path.write_text(("\n".join(remaining) + "\n") if remaining else "", encoding="utf-8")


def _validate_row(
    row: dict[str, Any],
    *,
    repeat_count: int,
    k_values: list[int],
    expected_context: str,
    expected_chunking: str,
) -> None:
    error_value = row.get("error")
    if isinstance(error_value, str) and error_value.strip():
        raise ValueError(f"matrix_rows reported error: {error_value}")

    for field in REQUIRED_ROW_NUMERIC_FIELDS:
        if not _is_finite_number(row.get(field)):
            raise ValueError(f"{field} must be a finite number")

    for field in REQUIRED_ROW_NUMERIC_LIST_FIELDS:
        values = row.get(field)
        if not isinstance(values, list):
            raise ValueError(f"{field} must be a list")
        if len(values) != repeat_count:
            raise ValueError(f"{field} length mismatch: expected {repeat_count}, found {len(values)}")
        if not all(_is_finite_number(value) for value in values):
            raise ValueError(f"{field} must contain only finite numbers")

    mean_cost = row.get("mean_generation_cost_usd")
    if mean_cost is not None and not _is_finite_number(mean_cost):
        raise ValueError("mean_generation_cost_usd must be a finite number or null")

    repeat_costs = row.get("repeat_generation_cost_usd")
    if not isinstance(repeat_costs, list):
        raise ValueError("repeat_generation_cost_usd must be a list")
    if len(repeat_costs) != repeat_count:
        raise ValueError(
            "repeat_generation_cost_usd length mismatch: "
            f"expected {repeat_count}, found {len(repeat_costs)}"
        )
    for cost in repeat_costs:
        if cost is not None and not _is_finite_number(cost):
            raise ValueError("repeat_generation_cost_usd must contain only finite numbers or null")

    pass_at_k = row.get("pass_at_k")
    if not isinstance(pass_at_k, dict):
        raise ValueError("pass_at_k must be an object")
    for k in k_values:
        key = str(k)
        if key not in pass_at_k:
            raise ValueError(f"pass_at_k missing key {key}")
        if not _is_finite_number(pass_at_k[key]):
            raise ValueError(f"pass_at_k[{key}] must be a finite number")

    if row.get("context_source") != expected_context:
        raise ValueError("context_source mismatch between config and matrix_rows")
    if row.get("chunking_strategy") != expected_chunking:
        raise ValueError("chunking_strategy mismatch between config and matrix_rows")
    if expected_context == "ast" and expected_chunking != "ast":
        raise ValueError("Invalid run: context_source='ast' requires chunking_strategy='ast'")


def _validate_outputs(
    *,
    config: dict[str, Any],
    matrix_rows_path: Path,
) -> None:
    raw_rows = json.loads(matrix_rows_path.read_text(encoding="utf-8"))
    if not isinstance(raw_rows, list):
        raise ValueError(f"matrix_rows.json must be a list: {matrix_rows_path}")
    if len(raw_rows) != 1:
        raise ValueError(f"Expected exactly 1 matrix row, found {len(raw_rows)}")
    row = raw_rows[0]
    if not isinstance(row, dict):
        raise ValueError("matrix row must be an object")

    repeat_count = int(config["repeat_count"])
    k_values = [int(value) for value in config["k_values"]]
    expected_context = str(config["context_sources"][0])
    expected_chunking = str(config["chunking_strategies"][0])

    _validate_row(
        row,
        repeat_count=repeat_count,
        k_values=k_values,
        expected_context=expected_context,
        expected_chunking=expected_chunking,
    )

    # Keep this tuple to enforce explicit handling and avoid accidental drift.
    _ = OPTIONAL_COST_FIELDS


def _build_command(
    *,
    config_path: Path,
    output_root: Path,
    workspace_root: Path,
    predictions_root: Path,
    runs_root: Path,
    artifacts_root: Path,
    skip_index: bool,
    skip_wiki_preparation: bool,
    skip_synthetic_validation: bool,
    ingestion_url: str,
    search_url: str,
) -> tuple[list[str], Path]:
    config_stem = _slug(config_path.stem)
    # Keep run prefixes short to avoid per-file path component length overflows.
    run_prefix = _short_run_prefix(config_path)
    matrix_out = output_root / config_stem
    matrix_out.mkdir(parents=True, exist_ok=True)

    command = [
        "uv",
        "run",
        "--package",
        "eval",
        "eval",
        "run-synthetic-matrix",
        "--config",
        str(config_path),
        "--run-prefix",
        run_prefix,
        "--max-parallel-cells",
        "1",
        "--output-root",
        str(matrix_out),
        "--workspace-root",
        str(workspace_root),
        "--predictions-root",
        str(predictions_root),
        "--runs-root",
        str(runs_root),
        "--artifacts-root",
        str(artifacts_root),
        "--ingestion-url",
        ingestion_url,
        "--search-url",
        search_url,
    ]
    if skip_index:
        command.append("--skip-index")
    if skip_wiki_preparation:
        command.append("--skip-wiki-preparation")
    if skip_synthetic_validation:
        command.append("--skip-validation")
    return command, matrix_out / "matrix_rows.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one singleton synthetic matrix config, validate numeric outputs, "
            "and remove it from pending queue on success."
        )
    )
    parser.add_argument("--pending", default=str(PENDING_PATH), help="Path to pending config list")
    parser.add_argument(
        "--config",
        default=None,
        help="Explicit config path. If omitted, use the first entry in --pending.",
    )
    parser.add_argument(
        "--pop-explicit-config",
        action="store_true",
        help="Also remove --config from pending list when --config is provided explicitly.",
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--workspace-root", default=str(DEFAULT_WORKSPACE_ROOT))
    parser.add_argument("--predictions-root", default=str(DEFAULT_PREDICTIONS_ROOT))
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--artifacts-root", default=str(DEFAULT_ARTIFACTS_ROOT))
    parser.add_argument("--ingestion-url", default="http://localhost:8001")
    parser.add_argument("--search-url", default="http://localhost:8002")
    parser.add_argument(
        "--allow-index",
        action="store_true",
        help="Allow indexing/wiki regeneration for this run (default is skip both).",
    )
    parser.add_argument(
        "--skip-synthetic-validation",
        action="store_true",
        help=(
            "Forward --skip-validation to run-synthetic-matrix. "
            "Use as an unblock when a known synthetic task patch is broken."
        ),
    )
    parser.add_argument(
        "--completed-runs-file",
        default=None,
        help=(
            "Optional file of run_id lines (e.g. runs.txt). If matrix_rows.json is missing but "
            "lighthouse summaries under --runs-root match this config with full repeat coverage, "
            "the config is popped from the queue without rerunning."
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    pending_path = Path(args.pending).resolve()
    output_root = Path(args.output_root).resolve()
    workspace_root = Path(args.workspace_root).resolve()
    predictions_root = Path(args.predictions_root).resolve()
    runs_root = Path(args.runs_root).resolve()
    artifacts_root = Path(args.artifacts_root).resolve()

    for root in (output_root, workspace_root, predictions_root, runs_root, artifacts_root):
        root.mkdir(parents=True, exist_ok=True)

    if args.config:
        config_path = Path(args.config).resolve()
        should_pop = bool(args.pop_explicit_config)
    else:
        if not pending_path.is_file():
            print(f"Pending config list does not exist: {pending_path}", file=sys.stderr)
            return 1
        try:
            config_path = _next_pending_config(pending_path)
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1
        should_pop = True

    if not config_path.is_file():
        print(f"Config not found: {config_path}", file=sys.stderr)
        return 1

    config = _read_config(config_path)
    try:
        _validate_config_bounds(config, config_path)
    except Exception as exc:
        print(f"Config validation failed: {exc}", file=sys.stderr)
        return 1
    command, matrix_rows_path = _build_command(
        config_path=config_path,
        output_root=output_root,
        workspace_root=workspace_root,
        predictions_root=predictions_root,
        runs_root=runs_root,
        artifacts_root=artifacts_root,
        skip_index=not args.allow_index,
        skip_wiki_preparation=not args.allow_index,
        skip_synthetic_validation=args.skip_synthetic_validation,
        ingestion_url=args.ingestion_url,
        search_url=args.search_url,
    )

    if matrix_rows_path.is_file():
        try:
            _validate_outputs(config=config, matrix_rows_path=matrix_rows_path)
        except Exception as exc:
            print(
                f"Existing matrix_rows failed validation, will rerun: {exc}",
                file=sys.stderr,
            )
        else:
            if should_pop:
                try:
                    _remove_config_from_pending(pending_path, config_path)
                except Exception as exc:
                    print(f"Queue update failed: {exc}", file=sys.stderr)
                    return 1
                print(
                    "Skipped run (validated matrix_rows.json already present): "
                    f"{config_path.relative_to(REPO_ROOT)}"
                )
            else:
                print("Validated existing matrix_rows.json (explicit config; queue unchanged).")
            return 0

    completed_runs_path = (
        Path(args.completed_runs_file).resolve() if args.completed_runs_file else None
    )
    if completed_runs_path is not None:
        historical_ids = load_run_id_list(completed_runs_path)
        matched = list_completed_lighthouse_summaries(
            run_ids=historical_ids,
            runs_root=runs_root,
            config=config,
        )
        repeat_count = int(config["repeat_count"])
        if matched and has_full_repeat_coverage(matched, repeat_count=repeat_count):
            if should_pop:
                try:
                    _remove_config_from_pending(pending_path, config_path)
                except Exception as exc:
                    print(f"Queue update failed: {exc}", file=sys.stderr)
                    return 1
                try:
                    hist_label = str(completed_runs_path.relative_to(REPO_ROOT))
                except ValueError:
                    hist_label = str(completed_runs_path)
                print(
                    "Skipped run (historical lighthouse summaries + repeat coverage via "
                    f"{hist_label}): "
                    f"{config_path.relative_to(REPO_ROOT)}"
                )
            else:
                print(
                    "Historical summaries match config with full repeat coverage "
                    "(explicit config; queue unchanged)."
                )
            return 0

    print(f"Running config: {config_path.relative_to(REPO_ROOT)}")
    print("Command:")
    print(" ".join(command))
    completed = subprocess.run(command, cwd=REPO_ROOT)
    if completed.returncode != 0:
        print(f"Eval command failed with exit code {completed.returncode}", file=sys.stderr)
        return 1

    if not matrix_rows_path.is_file():
        print(f"Missing matrix rows output: {matrix_rows_path}", file=sys.stderr)
        return 1

    try:
        _validate_outputs(config=config, matrix_rows_path=matrix_rows_path)
    except Exception as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 1

    if should_pop:
        try:
            _remove_config_from_pending(pending_path, config_path)
        except Exception as exc:
            print(f"Queue update failed: {exc}", file=sys.stderr)
            return 1
        print(f"Marked complete and removed from queue: {config_path.relative_to(REPO_ROOT)}")
    else:
        print("Validation passed (explicit config mode; queue unchanged).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
