from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from eval.compare import SWEBenchPassAtKSummary, SWEBenchScoreRow


@dataclass(frozen=True)
class HeatmapConfig:
    title: str
    row_labels: tuple[str, ...]
    column_labels: tuple[str, ...]
    values: tuple[tuple[float, ...], ...]
    output_path: Path
    color_map: str = "YlGn"
    value_format: str = "{:.1f}%"


def generate_score_heatmap(
    *,
    score_rows_by_repo: dict[str, Sequence[SWEBenchScoreRow]],
    output_path: Path,
) -> Path:
    repo_names = sorted(score_rows_by_repo.keys())
    if not repo_names:
        raise ValueError("No repos provided for score heatmap generation.")

    first_rows = score_rows_by_repo[repo_names[0]]
    column_labels = tuple(row.label for row in first_rows)

    values: list[tuple[float, ...]] = []
    for repo in repo_names:
        rows = score_rows_by_repo[repo]
        values.append(tuple(row.score_pct for row in rows))

    config = HeatmapConfig(
        title="SWE-bench Score by Repository",
        row_labels=tuple(repo_names),
        column_labels=column_labels,
        values=tuple(values),
        output_path=output_path,
    )
    return _render_heatmap(config)


def generate_pass_at_k_heatmap(
    *,
    pass_at_k_by_repo: dict[str, SWEBenchPassAtKSummary],
    output_path: Path,
) -> Path:
    repo_names = sorted(pass_at_k_by_repo.keys())
    if not repo_names:
        raise ValueError("No repos provided for pass@k heatmap generation.")

    first_summary = pass_at_k_by_repo[repo_names[0]]
    column_labels = tuple(f"pass@{k}" for k in first_summary.k_values)

    values: list[tuple[float, ...]] = []
    for repo in repo_names:
        summary = pass_at_k_by_repo[repo]
        macro = dict(summary.macro_pass_at_k)
        values.append(tuple(macro[k] * 100.0 for k in summary.k_values))

    config = HeatmapConfig(
        title="SWE-bench Pass@k by Repository",
        row_labels=tuple(repo_names),
        column_labels=column_labels,
        values=tuple(values),
        output_path=output_path,
    )
    return _render_heatmap(config)


def _render_heatmap(config: HeatmapConfig) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    data = np.array(config.values)
    n_rows, n_cols = data.shape

    fig_width = max(4, n_cols * 1.8 + 2)
    fig_height = max(3, n_rows * 0.8 + 2)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    im = ax.imshow(data, cmap=config.color_map, aspect="auto", vmin=0, vmax=100)

    ax.set_xticks(range(n_cols))
    ax.set_xticklabels(config.column_labels, rotation=45, ha="right")
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(config.row_labels)

    for i in range(n_rows):
        for j in range(n_cols):
            text_color = "white" if data[i, j] > 70 else "black"
            ax.text(
                j,
                i,
                config.value_format.format(data[i, j]),
                ha="center",
                va="center",
                color=text_color,
                fontsize=9,
            )

    ax.set_title(config.title, pad=12)
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()

    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(config.output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)

    return config.output_path
