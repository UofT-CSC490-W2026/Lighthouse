from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from eval.historical_runs import (
    list_completed_lighthouse_summaries,
    load_run_id_list,
    rollup_lighthouse_summaries,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_GLOB = "eval/configs/generated/*.json"
DEFAULT_MATRIX_ROOT = REPO_ROOT / ".cache" / "eval" / "synthetic_experiments" / "queued" / "matrix"
DEFAULT_OUTPUT_JSON = REPO_ROOT / "eval" / "results" / "aggregated_matrix_rows.json"
DEFAULT_OUTPUT_CSV = REPO_ROOT / "eval" / "results" / "aggregated_matrix_rows.csv"
DEFAULT_RUNS_ROOT = REPO_ROOT / ".cache" / "eval" / "synthetic_runs" / "queued"
DEFAULT_HISTORICAL_RUNS_FILE = REPO_ROOT / "runs.txt"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _singleton(config: dict[str, Any], key: str) -> str:
    values = config.get(key)
    if not isinstance(values, list) or len(values) != 1:
        raise ValueError(f"{key} must be singleton list")
    return str(values[0])


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


def _config_stem(config_path: Path) -> str:
    return _slug(config_path.stem)


def _pass_at_fields(row: dict[str, Any], k_values: list[int]) -> dict[str, Any]:
    pass_map = row.get("pass_at_k", {})
    if not isinstance(pass_map, dict):
        pass_map = {}
    return {f"pass_at_{k}": pass_map.get(str(k)) for k in k_values}


def _per_query(
    *,
    mean_total_duration_seconds: float | None,
    mean_generation_cost_usd: float | None,
    task_count: int,
) -> tuple[float | None, float | None]:
    if task_count <= 0:
        return None, None
    lat = (
        None
        if mean_total_duration_seconds is None
        else float(mean_total_duration_seconds) / task_count
    )
    cost = (
        None
        if mean_generation_cost_usd is None
        else float(mean_generation_cost_usd) / task_count
    )
    return lat, cost


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate queued singleton matrix outputs into one JSON and CSV."
    )
    parser.add_argument("--config-glob", default=DEFAULT_CONFIG_GLOB)
    parser.add_argument("--matrix-root", default=str(DEFAULT_MATRIX_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV))
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument(
        "--historical-runs-file",
        default=str(DEFAULT_HISTORICAL_RUNS_FILE),
        help="Newline-delimited run_ids merged when matrix_rows.json is missing (default: runs.txt).",
    )
    parser.add_argument(
        "--skip-historical-runs",
        action="store_true",
        help="Only use matrix_rows.json (ignore --historical-runs-file).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if any config is missing matrix_rows.json and historical fallback",
    )
    return parser


def _base_record_fields(
    *,
    config_path: Path,
    matrix_rows_path: str | None,
    config: dict[str, Any],
    row: dict[str, Any],
    provenance: str,
) -> dict[str, Any]:
    k_values = [int(value) for value in config["k_values"]]
    mean_dur = row.get("mean_total_duration_seconds")
    mean_cost = row.get("mean_generation_cost_usd")
    task_count = int(config["task_count"])
    lat_q, cost_q = _per_query(
        mean_total_duration_seconds=float(mean_dur) if mean_dur is not None else None,
        mean_generation_cost_usd=float(mean_cost) if mean_cost is not None else None,
        task_count=task_count,
    )
    record: dict[str, Any] = {
        "config_path": str(config_path.relative_to(REPO_ROOT)),
        "matrix_rows_path": matrix_rows_path or "",
        "provenance": provenance,
        "family": _singleton(config, "families"),
        "context_source": _singleton(config, "context_sources"),
        "chunking_strategy": _singleton(config, "chunking_strategies"),
        "codegen_model": _singleton(config, "codegen_models"),
        "embedding_strategy": str(config["embedding_strategy"]),
        "embedding_model": _singleton(config, "embedding_models"),
        "repeat_count": int(config["repeat_count"]),
        "task_count": task_count,
        "top_k": int(config["top_k"]),
        "k_values": json.dumps(config["k_values"]),
        "mean_score_pct": row.get("mean_score_pct"),
        "score_pct": row.get("mean_score_pct"),
        "stddev_score_pct": row.get("stddev_score_pct"),
        "mean_total_duration_seconds": row.get("mean_total_duration_seconds"),
        "mean_generation_total_tokens": row.get("mean_generation_total_tokens"),
        "mean_generation_cost_usd": row.get("mean_generation_cost_usd"),
        "avg_latency_per_query_s": lat_q,
        "avg_cost_per_query_usd": cost_q,
        "error": row.get("error"),
        "run_ids": json.dumps(row.get("run_ids", [])),
        "baseline_run_ids": json.dumps(row.get("baseline_run_ids", [])),
    }
    record.update(_pass_at_fields(row, k_values))
    return record


def main() -> int:
    args = build_parser().parse_args()
    matrix_root = Path(args.matrix_root).resolve()
    output_json = Path(args.output_json).resolve()
    output_csv = Path(args.output_csv).resolve()
    runs_root = Path(args.runs_root).resolve()

    if args.skip_historical_runs:
        historical_ids: tuple[str, ...] = ()
    else:
        hist_arg = str(args.historical_runs_file or "").strip()
        historical_path = Path(hist_arg).resolve() if hist_arg else None
        historical_ids = load_run_id_list(historical_path) if historical_path else ()

    config_paths = sorted(REPO_ROOT.glob(args.config_glob))
    if not config_paths:
        raise RuntimeError(f"No config files matched: {args.config_glob}")

    records: list[dict[str, Any]] = []
    missing: list[str] = []
    for config_path in config_paths:
        config = _read_json(config_path)
        if not isinstance(config, dict):
            raise ValueError(f"Config must be object: {config_path}")

        stem = _config_stem(config_path)
        matrix_rows_path = matrix_root / stem / "matrix_rows.json"
        if matrix_rows_path.is_file():
            rows = _read_json(matrix_rows_path)
            if not isinstance(rows, list):
                raise ValueError(f"matrix_rows.json must be list: {matrix_rows_path}")
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f"matrix row must be object: {matrix_rows_path}")
                records.append(
                    _base_record_fields(
                        config_path=config_path,
                        matrix_rows_path=str(matrix_rows_path.relative_to(REPO_ROOT)),
                        config=config,
                        row=row,
                        provenance="matrix",
                    )
                )
            continue

        if not historical_ids:
            missing.append(str(config_path.relative_to(REPO_ROOT)))
            continue

        matched = list_completed_lighthouse_summaries(
            run_ids=historical_ids,
            runs_root=runs_root,
            config=config,
        )
        rollup = rollup_lighthouse_summaries(matched, config=config)
        if rollup is None:
            missing.append(str(config_path.relative_to(REPO_ROOT)))
            continue

        pseudo_row: dict[str, Any] = {
            "mean_score_pct": rollup.mean_score_pct,
            "stddev_score_pct": None,
            "mean_total_duration_seconds": rollup.mean_total_duration_seconds,
            "mean_generation_total_tokens": None,
            "mean_generation_cost_usd": rollup.mean_generation_cost_usd,
            "pass_at_k": {},
            "error": None,
            "run_ids": list(rollup.provenance_run_ids),
            "baseline_run_ids": [],
        }
        records.append(
            _base_record_fields(
                config_path=config_path,
                matrix_rows_path="",
                config=config,
                row=pseudo_row,
                provenance="historical",
            )
        )

    if missing and args.strict:
        missing_str = ", ".join(missing[:10])
        raise RuntimeError(
            f"Missing matrix/historical rows for {len(missing)} configs. Examples: {missing_str}"
        )

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    fieldnames: list[str] = []
    for record in records:
        for key in record:
            if key not in fieldnames:
                fieldnames.append(key)
    if not fieldnames:
        fieldnames = [
            "config_path",
            "matrix_rows_path",
            "provenance",
            "family",
            "context_source",
            "chunking_strategy",
            "codegen_model",
            "embedding_strategy",
            "embedding_model",
            "repeat_count",
            "task_count",
            "top_k",
            "k_values",
            "mean_score_pct",
            "score_pct",
            "stddev_score_pct",
            "mean_total_duration_seconds",
            "mean_generation_total_tokens",
            "mean_generation_cost_usd",
            "avg_latency_per_query_s",
            "avg_cost_per_query_usd",
            "pass_at_1",
            "error",
            "run_ids",
            "baseline_run_ids",
        ]

    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    print(f"Configs scanned: {len(config_paths)}")
    print(f"Rows aggregated: {len(records)}")
    print(f"Missing matrix rows: {len(missing)}")
    print(f"Wrote JSON: {output_json}")
    print(f"Wrote CSV: {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
