from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_GLOB = "eval/configs/generated/*.json"
DEFAULT_MATRIX_ROOT = REPO_ROOT / ".cache" / "eval" / "synthetic_experiments" / "queued" / "matrix"
DEFAULT_OUTPUT_JSON = REPO_ROOT / "eval" / "results" / "aggregated_matrix_rows.json"
DEFAULT_OUTPUT_CSV = REPO_ROOT / "eval" / "results" / "aggregated_matrix_rows.csv"


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate queued singleton matrix outputs into one JSON and CSV."
    )
    parser.add_argument("--config-glob", default=DEFAULT_CONFIG_GLOB)
    parser.add_argument("--matrix-root", default=str(DEFAULT_MATRIX_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV))
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if any config is missing matrix_rows.json",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    matrix_root = Path(args.matrix_root).resolve()
    output_json = Path(args.output_json).resolve()
    output_csv = Path(args.output_csv).resolve()

    config_paths = sorted(REPO_ROOT.glob(args.config_glob))
    if not config_paths:
        raise RuntimeError(f"No config files matched: {args.config_glob}")

    records: list[dict[str, Any]] = []
    missing: list[str] = []
    for config_path in config_paths:
        config = _read_json(config_path)
        stem = _config_stem(config_path)
        matrix_rows_path = matrix_root / stem / "matrix_rows.json"
        if not matrix_rows_path.is_file():
            missing.append(str(config_path.relative_to(REPO_ROOT)))
            continue

        rows = _read_json(matrix_rows_path)
        if not isinstance(rows, list):
            raise ValueError(f"matrix_rows.json must be list: {matrix_rows_path}")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"matrix row must be object: {matrix_rows_path}")
            pass_map = row.get("pass_at_k", {})
            if not isinstance(pass_map, dict):
                pass_map = {}
            record = {
                "config_path": str(config_path.relative_to(REPO_ROOT)),
                "matrix_rows_path": str(matrix_rows_path.relative_to(REPO_ROOT)),
                "family": _singleton(config, "families"),
                "context_source": _singleton(config, "context_sources"),
                "chunking_strategy": _singleton(config, "chunking_strategies"),
                "codegen_model": _singleton(config, "codegen_models"),
                "embedding_strategy": str(config["embedding_strategy"]),
                "embedding_model": _singleton(config, "embedding_models"),
                "repeat_count": int(config["repeat_count"]),
                "task_count": int(config["task_count"]),
                "top_k": int(config["top_k"]),
                "k_values": json.dumps(config["k_values"]),
                "mean_score_pct": row.get("mean_score_pct"),
                "stddev_score_pct": row.get("stddev_score_pct"),
                "mean_total_duration_seconds": row.get("mean_total_duration_seconds"),
                "mean_generation_total_tokens": row.get("mean_generation_total_tokens"),
                "mean_generation_cost_usd": row.get("mean_generation_cost_usd"),
                "pass_at_1": pass_map.get("1"),
                "pass_at_2": pass_map.get("2"),
                "pass_at_3": pass_map.get("3"),
                "error": row.get("error"),
                "run_ids": json.dumps(row.get("run_ids", [])),
                "baseline_run_ids": json.dumps(row.get("baseline_run_ids", [])),
            }
            records.append(record)

    if missing and args.strict:
        missing_str = ", ".join(missing[:10])
        raise RuntimeError(f"Missing matrix rows for {len(missing)} configs. Examples: {missing_str}")

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if records:
        fieldnames = list(records[0].keys())
    else:
        fieldnames = [
            "config_path",
            "matrix_rows_path",
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
            "stddev_score_pct",
            "mean_total_duration_seconds",
            "mean_generation_total_tokens",
            "mean_generation_cost_usd",
            "pass_at_1",
            "pass_at_2",
            "pass_at_3",
            "error",
            "run_ids",
            "baseline_run_ids",
        ]

    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
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
