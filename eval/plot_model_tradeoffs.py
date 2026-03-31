from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import csv

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_CSV = REPO_ROOT / "eval" / "results" / "aggregated_matrix_rows.csv"
DEFAULT_PLOT_DIR = REPO_ROOT / "eval" / "results" / "plots"
DEFAULT_POINTS_CSV = REPO_ROOT / "eval" / "results" / "plots" / "model_method_tradeoff_points.csv"


def _float_cell(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _short_model(name: str) -> str:
    text = name.strip()
    for prefix in ("bedrock/", "openai/"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.replace("/", "-")[:48]


def aggregate_points(
    rows: list[dict[str, str]],
    *,
    methods: frozenset[str],
) -> list[dict[str, object]]:
    """One row per (codegen_model, context_source) after averaging over families."""
    buckets: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        method = row.get("context_source", "").strip()
        if method not in methods:
            continue
        model = row.get("codegen_model", "").strip()
        if not model:
            continue
        buckets[(model, method)].append(row)

    out: list[dict[str, object]] = []
    for (model, method), group in sorted(buckets.items()):
        scores: list[float] = []
        lats: list[float] = []
        costs: list[float] = []
        families: list[str] = []
        for item in group:
            sc = _float_cell(item.get("mean_score_pct", "") or item.get("score_pct", ""))
            lat = _float_cell(item.get("avg_latency_per_query_s", ""))
            cost = _float_cell(item.get("avg_cost_per_query_usd", ""))
            fam = item.get("family", "").strip()
            if sc is not None:
                scores.append(sc)
            if lat is not None:
                lats.append(lat)
            if cost is not None:
                costs.append(cost)
            if fam:
                families.append(fam)
        if not scores:
            continue
        out.append(
            {
                "codegen_model": model,
                "model_label": _short_model(model),
                "method": method,
                "n_families": len(group),
                "mean_score_pct": sum(scores) / len(scores),
                "mean_avg_latency_per_query_s": sum(lats) / len(lats) if lats else None,
                "mean_avg_cost_per_query_usd": sum(costs) / len(costs) if costs else None,
                "families": ";".join(sorted(set(families))),
            }
        )
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Latency/score and cost/score scatter plots (combined vs grep by marker style)."
    )
    p.add_argument("--input-csv", default=str(DEFAULT_INPUT_CSV))
    p.add_argument("--output-dir", default=str(DEFAULT_PLOT_DIR))
    p.add_argument("--points-csv", default=str(DEFAULT_POINTS_CSV))
    p.add_argument(
        "--methods",
        default="combined,grep",
        help="Comma-separated context_source values to include.",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    input_csv = Path(args.input_csv).resolve()
    output_dir = Path(args.output_dir).resolve()
    points_csv = Path(args.points_csv).resolve()
    methods = frozenset(m.strip() for m in args.methods.split(",") if m.strip())

    if not input_csv.is_file():
        raise SystemExit(f"Missing aggregated CSV: {input_csv}")

    with input_csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    points = aggregate_points(rows, methods=methods)
    output_dir.mkdir(parents=True, exist_ok=True)
    points_csv.parent.mkdir(parents=True, exist_ok=True)

    if not points:
        print("No rows matched --methods filter; no plots written.")
        points_csv.write_text(
            "codegen_model,model_label,method,n_families,mean_score_pct,"
            "mean_avg_latency_per_query_s,mean_avg_cost_per_query_usd,families\n",
            encoding="utf-8",
        )
        return 0

    fieldnames = [
        "codegen_model",
        "model_label",
        "method",
        "n_families",
        "mean_score_pct",
        "mean_avg_latency_per_query_s",
        "mean_avg_cost_per_query_usd",
        "families",
    ]
    with points_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in points:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit(
            "matplotlib is required for plots. Install dev deps: uv sync --all-packages --dev"
        ) from exc

    by_model: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    for row in points:
        by_model[str(row["codegen_model"])][str(row["method"])] = row

    def _scatter(
        *,
        x_key: str,
        title: str,
        x_label: str,
        out_name: str,
    ) -> None:
        any_point = False
        for _model, method_map in by_model.items():
            for method in methods:
                cell = method_map.get(method)
                if not cell:
                    continue
                xv = cell.get(x_key)
                yv = cell.get("mean_score_pct")
                if xv is not None and yv is not None:
                    any_point = True
                    break
            if any_point:
                break
        if not any_point:
            print(f"Skipping plot {out_name}: no finite {x_key} values for selected methods.")
            return

        fig, ax = plt.subplots(figsize=(9, 6))
        for method in sorted(methods):
            xs: list[float] = []
            ys: list[float] = []
            labels: list[str] = []
            for model, method_map in sorted(by_model.items(), key=lambda kv: kv[0]):
                cell = method_map.get(method)
                if cell is None:
                    continue
                xv = cell.get(x_key)
                yv = cell.get("mean_score_pct")
                if xv is None or yv is None:
                    continue
                xs.append(float(xv))
                ys.append(float(yv))
                labels.append(str(cell["model_label"]))
            if not xs:
                continue
            if method == "combined":
                facecolors, edgecolors = "C0", "C0"
            else:
                facecolors, edgecolors = "none", "C1"
            ax.scatter(
                xs,
                ys,
                s=80,
                label=method,
                marker="o",
                facecolors=facecolors,
                edgecolors=edgecolors,
                linewidths=1.8,
            )
            for x, y, lab in zip(xs, ys, labels, strict=True):
                ax.annotate(lab, (x, y), textcoords="offset points", xytext=(4, 4), fontsize=7)

        for model, method_map in by_model.items():
            if "combined" in method_map and "grep" in method_map:
                a = method_map["combined"]
                b = method_map["grep"]
                xa, ya = a.get(x_key), a.get("mean_score_pct")
                xb, yb = b.get(x_key), b.get("mean_score_pct")
                if xa is not None and ya is not None and xb is not None and yb is not None:
                    ax.plot(
                        [float(xa), float(xb)],
                        [float(ya), float(yb)],
                        color="0.65",
                        linestyle=":",
                        linewidth=1,
                        zorder=0,
                    )

        ax.set_xlabel(x_label)
        ax.set_ylabel("Score")
        ax.set_title(title)
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(output_dir / out_name, dpi=160)
        plt.close(fig)

    _scatter(
        x_key="mean_avg_latency_per_query_s",
        title="Latency vs Score",
        x_label="Average latency / Query",
        out_name="score_vs_latency_per_query.png",
    )
    _scatter(
        x_key="mean_avg_cost_per_query_usd",
        title="Cost vs Score",
        x_label="Average cost / Query",
        out_name="score_vs_cost_per_query.png",
    )

    print(f"Wrote points CSV: {points_csv}")
    print(f"Wrote plots under: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
