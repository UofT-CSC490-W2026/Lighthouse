from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
from typing import Any

from .compare import compute_synthetic_pass_at_k, render_synthetic_pass_at_k_table
from .experiment import (
    DEFAULT_SYNTHETIC_EXPERIMENT_ARTIFACTS_ROOT,
    DEFAULT_SYNTHETIC_PREDICTIONS_ROOT,
    run_synthetic_experiment,
)
from .workspace import DEFAULT_SYNTHETIC_RUNS_ROOT, load_synthetic_family

_VALID_CONTEXT_SOURCES = {"code", "wiki", "ast", "combined", "code+wiki"}
_VALID_CHUNKING_STRATEGIES = {"base", "ast"}
_SAFE_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class SyntheticMatrixConfig:
    families: tuple[str, ...]
    context_sources: tuple[str, ...]
    chunking_strategies: tuple[str, ...]
    codegen_models: tuple[str, ...]
    embedding_models: tuple[str, ...]
    embedding_strategy: str
    repeat_count: int
    k_values: tuple[int, ...]
    task_count: int | None
    task_type: str | None
    seed: int | None
    shared_library_repo_count: int | None
    top_k: int


@dataclass(frozen=True)
class SyntheticMatrixCellSpec:
    family_name: str
    context_source: str
    chunking_strategy: str
    codegen_model: str
    embedding_model: str


@dataclass(frozen=True)
class SyntheticMatrixCellResult:
    spec: SyntheticMatrixCellSpec
    run_ids: tuple[str, ...]
    baseline_run_ids: tuple[str, ...]
    repeat_scores_pct: tuple[float, ...]
    mean_score_pct: float
    stddev_score_pct: float
    repeat_total_duration_seconds: tuple[float, ...]
    mean_total_duration_seconds: float
    repeat_generation_total_tokens: tuple[int, ...]
    mean_generation_total_tokens: float
    repeat_generation_cost_usd: tuple[float | None, ...]
    mean_generation_cost_usd: float | None
    pass_at_k: tuple[tuple[int, float], ...]
    pass_at_k_table_path: Path | None
    error: str | None


@dataclass(frozen=True)
class SyntheticMatrixResult:
    config: SyntheticMatrixConfig
    output_root: Path
    rows_json_path: Path
    rows_markdown_path: Path
    efficiency_json_path: Path
    efficiency_text_path: Path
    heatmap_paths: tuple[Path, ...]
    cell_results: tuple[SyntheticMatrixCellResult, ...]


def load_synthetic_matrix_config(path: Path) -> SyntheticMatrixConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Matrix config must be a JSON object.")

    families = _as_non_empty_str_tuple(payload.get("families"), field_name="families")
    context_sources = _as_non_empty_str_tuple(
        payload.get("context_sources"),
        field_name="context_sources",
    )
    chunking_strategies = _as_non_empty_str_tuple(
        payload.get("chunking_strategies"),
        field_name="chunking_strategies",
    )
    codegen_models = _as_non_empty_str_tuple(
        payload.get("codegen_models"),
        field_name="codegen_models",
    )
    embedding_models = _as_non_empty_str_tuple(
        payload.get("embedding_models"),
        field_name="embedding_models",
    )
    for source in context_sources:
        if source not in _VALID_CONTEXT_SOURCES:
            raise ValueError(f"Unsupported context source: {source!r}")
    for strategy in chunking_strategies:
        if strategy not in _VALID_CHUNKING_STRATEGIES:
            raise ValueError(f"Unsupported chunking strategy: {strategy!r}")

    embedding_strategy = str(payload.get("embedding_strategy", "openai")).strip()
    if not embedding_strategy:
        raise ValueError("embedding_strategy must not be empty.")

    repeat_count = int(payload.get("repeat_count", 1))
    if repeat_count < 1:
        raise ValueError("repeat_count must be at least 1.")

    raw_k = payload.get("k_values", [1])
    if not isinstance(raw_k, list):
        raise ValueError("k_values must be a list of integers.")
    k_values = tuple(sorted({int(value) for value in raw_k if int(value) > 0}))
    if not k_values:
        raise ValueError("k_values must include at least one positive integer.")

    task_count = _optional_int(payload.get("task_count"))
    task_type = _optional_str(payload.get("task_type"))
    seed = _optional_int(payload.get("seed"))
    shared_library_repo_count = _optional_int(payload.get("shared_library_repo_count"))
    top_k = int(payload.get("top_k", 5))
    if top_k < 1:
        raise ValueError("top_k must be at least 1.")

    return SyntheticMatrixConfig(
        families=families,
        context_sources=context_sources,
        chunking_strategies=chunking_strategies,
        codegen_models=codegen_models,
        embedding_models=embedding_models,
        embedding_strategy=embedding_strategy,
        repeat_count=repeat_count,
        k_values=k_values,
        task_count=task_count,
        task_type=task_type,
        seed=seed,
        shared_library_repo_count=shared_library_repo_count,
        top_k=top_k,
    )


def run_synthetic_matrix(
    *,
    config: SyntheticMatrixConfig,
    run_prefix: str,
    output_root: Path,
    workspace_root: Path,
    predictions_root: Path = DEFAULT_SYNTHETIC_PREDICTIONS_ROOT,
    runs_root: Path = DEFAULT_SYNTHETIC_RUNS_ROOT,
    artifacts_root: Path = DEFAULT_SYNTHETIC_EXPERIMENT_ARTIFACTS_ROOT,
    overwrite: bool = False,
    validate_workspace: bool = True,
    skip_index: bool = False,
    skip_wiki_preparation: bool = False,
    ingestion_url: str = "http://localhost:8001",
    search_service_url: str = "http://localhost:8002",
    github_token: str | None = None,
    stream_worker_logs: bool | None = None,
    index_poll_interval_seconds: float = 2.0,
    index_progress_heartbeat_seconds: float = 10.0,
    index_timeout_seconds: float = 900.0,
    wiki_poll_interval_seconds: float = 2.0,
    wiki_progress_heartbeat_seconds: float = 10.0,
    wiki_timeout_seconds: float = 900.0,
    region_name: str = "us-east-1",
    temperature: float = 0.0,
    max_tokens: int = 4096,
    dry_run: bool = False,
    continue_on_error: bool = False,
) -> SyntheticMatrixResult:
    if not run_prefix.strip():
        raise ValueError("run_prefix must not be empty.")
    resolved_output_root = output_root.resolve()
    resolved_output_root.mkdir(parents=True, exist_ok=True)
    families = _resolve_families(config.families)
    cell_specs = expand_matrix_cell_specs(config=config, families=families)

    results: list[SyntheticMatrixCellResult] = []
    for spec in cell_specs:
        if dry_run:
            results.append(
                SyntheticMatrixCellResult(
                    spec=spec,
                    run_ids=tuple(
                        _matrix_run_id(run_prefix, spec, rep + 1, retrieval=True)
                        for rep in range(config.repeat_count)
                    ),
                    baseline_run_ids=tuple(
                        _matrix_run_id(run_prefix, spec, rep + 1, retrieval=False)
                        for rep in range(config.repeat_count)
                    ),
                    repeat_scores_pct=(),
                    mean_score_pct=math.nan,
                    stddev_score_pct=math.nan,
                    repeat_total_duration_seconds=(),
                    mean_total_duration_seconds=math.nan,
                    repeat_generation_total_tokens=(),
                    mean_generation_total_tokens=math.nan,
                    repeat_generation_cost_usd=(),
                    mean_generation_cost_usd=None,
                    pass_at_k=(),
                    pass_at_k_table_path=None,
                    error=None,
                )
            )
            continue

        try:
            result = _run_cell(
                spec=spec,
                config=config,
                run_prefix=run_prefix,
                workspace_root=workspace_root,
                predictions_root=predictions_root,
                runs_root=runs_root,
                artifacts_root=artifacts_root,
                overwrite=overwrite,
                validate_workspace=validate_workspace,
                skip_index=skip_index,
                skip_wiki_preparation=skip_wiki_preparation,
                ingestion_url=ingestion_url,
                search_service_url=search_service_url,
                github_token=github_token,
                stream_worker_logs=stream_worker_logs,
                index_poll_interval_seconds=index_poll_interval_seconds,
                index_progress_heartbeat_seconds=index_progress_heartbeat_seconds,
                index_timeout_seconds=index_timeout_seconds,
                wiki_poll_interval_seconds=wiki_poll_interval_seconds,
                wiki_progress_heartbeat_seconds=wiki_progress_heartbeat_seconds,
                wiki_timeout_seconds=wiki_timeout_seconds,
                region_name=region_name,
                temperature=temperature,
                max_tokens=max_tokens,
                output_root=resolved_output_root,
            )
        except Exception as exc:
            if not continue_on_error:
                raise
            result = SyntheticMatrixCellResult(
                spec=spec,
                run_ids=(),
                baseline_run_ids=(),
                repeat_scores_pct=(),
                mean_score_pct=math.nan,
                stddev_score_pct=math.nan,
                repeat_total_duration_seconds=(),
                mean_total_duration_seconds=math.nan,
                repeat_generation_total_tokens=(),
                mean_generation_total_tokens=math.nan,
                repeat_generation_cost_usd=(),
                mean_generation_cost_usd=None,
                pass_at_k=(),
                pass_at_k_table_path=None,
                error=str(exc),
            )
        results.append(result)

    rows_json_path = resolved_output_root / "matrix_rows.json"
    rows_markdown_path = resolved_output_root / "matrix_rows.md"
    rows_json_path.write_text(
        json.dumps(
            [
                {
                    **asdict(result.spec),
                    "run_ids": list(result.run_ids),
                    "baseline_run_ids": list(result.baseline_run_ids),
                    "repeat_scores_pct": list(result.repeat_scores_pct),
                    "mean_score_pct": result.mean_score_pct,
                    "stddev_score_pct": result.stddev_score_pct,
                    "repeat_total_duration_seconds": list(result.repeat_total_duration_seconds),
                    "mean_total_duration_seconds": result.mean_total_duration_seconds,
                    "repeat_generation_total_tokens": list(result.repeat_generation_total_tokens),
                    "mean_generation_total_tokens": result.mean_generation_total_tokens,
                    "repeat_generation_cost_usd": list(result.repeat_generation_cost_usd),
                    "mean_generation_cost_usd": result.mean_generation_cost_usd,
                    "pass_at_k": {
                        str(k): value for k, value in result.pass_at_k
                    },
                    "pass_at_k_table_path": (
                        str(result.pass_at_k_table_path.resolve())
                        if result.pass_at_k_table_path is not None
                        else None
                    ),
                    "error": result.error,
                }
                for result in results
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    rows_markdown_path.write_text(
        "\n".join(
            [
                "Scores and Pass@k",
                render_matrix_rows_markdown(results).strip(),
                "",
                "Efficiency",
                render_matrix_efficiency_markdown(results).strip(),
                "",
            ]
        ),
        encoding="utf-8",
    )
    efficiency_json_path = resolved_output_root / "matrix_efficiency.json"
    efficiency_text_path = resolved_output_root / "matrix_efficiency.txt"
    efficiency_json_path.write_text(
        json.dumps(
            [
                {
                    **asdict(result.spec),
                    "mean_total_duration_seconds": result.mean_total_duration_seconds,
                    "mean_generation_total_tokens": result.mean_generation_total_tokens,
                    "mean_generation_cost_usd": result.mean_generation_cost_usd,
                    "repeat_total_duration_seconds": list(result.repeat_total_duration_seconds),
                    "repeat_generation_total_tokens": list(result.repeat_generation_total_tokens),
                    "repeat_generation_cost_usd": list(result.repeat_generation_cost_usd),
                    "error": result.error,
                }
                for result in results
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    efficiency_text_path.write_text(render_matrix_efficiency_markdown(results), encoding="utf-8")

    heatmap_paths = () if dry_run else _render_heatmaps(results, config, resolved_output_root)
    return SyntheticMatrixResult(
        config=config,
        output_root=resolved_output_root,
        rows_json_path=rows_json_path,
        rows_markdown_path=rows_markdown_path,
        efficiency_json_path=efficiency_json_path,
        efficiency_text_path=efficiency_text_path,
        heatmap_paths=heatmap_paths,
        cell_results=tuple(results),
    )


def expand_matrix_cell_specs(
    *,
    config: SyntheticMatrixConfig,
    families: Sequence[str] | None = None,
) -> tuple[SyntheticMatrixCellSpec, ...]:
    resolved_families = tuple(families) if families is not None else _resolve_families(config.families)
    specs: list[SyntheticMatrixCellSpec] = []
    for family_name in resolved_families:
        for context_source in config.context_sources:
            for chunking_strategy in config.chunking_strategies:
                for codegen_model in config.codegen_models:
                    for embedding_model in config.embedding_models:
                        specs.append(
                            SyntheticMatrixCellSpec(
                                family_name=family_name,
                                context_source=context_source,
                                chunking_strategy=chunking_strategy,
                                codegen_model=codegen_model,
                                embedding_model=embedding_model,
                            )
                        )
    return tuple(specs)


def render_matrix_rows_markdown(rows: Sequence[SyntheticMatrixCellResult]) -> str:
    headers = (
        "family",
        "context",
        "chunking",
        "codegen_model",
        "embedding_model",
        "mean_score_pct",
        "stddev_score_pct",
        "mean_duration_s",
        "mean_gen_tokens",
        "mean_gen_cost_usd",
        "pass_at_k",
        "error",
    )
    body_rows = []
    for row in rows:
        pass_at_k = ", ".join(f"{k}:{value * 100:.1f}%" for k, value in row.pass_at_k) or "-"
        body_rows.append(
            (
                row.spec.family_name,
                row.spec.context_source,
                row.spec.chunking_strategy,
                row.spec.codegen_model,
                row.spec.embedding_model,
                "-" if math.isnan(row.mean_score_pct) else f"{row.mean_score_pct:.2f}",
                "-" if math.isnan(row.stddev_score_pct) else f"{row.stddev_score_pct:.2f}",
                "-" if math.isnan(row.mean_total_duration_seconds) else f"{row.mean_total_duration_seconds:.2f}",
                "-" if math.isnan(row.mean_generation_total_tokens) else f"{row.mean_generation_total_tokens:.1f}",
                "-" if row.mean_generation_cost_usd is None else f"{row.mean_generation_cost_usd:.6f}",
                pass_at_k,
                row.error or "",
            )
        )
    return _render_table(headers, body_rows) + "\n"


def render_matrix_efficiency_markdown(rows: Sequence[SyntheticMatrixCellResult]) -> str:
    headers = (
        "family",
        "context",
        "chunking",
        "codegen_model",
        "embedding_model",
        "mean_duration_s",
        "mean_gen_tokens",
        "mean_gen_cost_usd",
        "error",
    )
    table_rows = []
    for row in rows:
        table_rows.append(
            (
                row.spec.family_name,
                row.spec.context_source,
                row.spec.chunking_strategy,
                row.spec.codegen_model,
                row.spec.embedding_model,
                "-" if math.isnan(row.mean_total_duration_seconds) else f"{row.mean_total_duration_seconds:.2f}",
                "-" if math.isnan(row.mean_generation_total_tokens) else f"{row.mean_generation_total_tokens:.1f}",
                "-" if row.mean_generation_cost_usd is None else f"{row.mean_generation_cost_usd:.6f}",
                row.error or "",
            )
        )
    return _render_table(headers, table_rows) + "\n"


def _run_cell(
    *,
    spec: SyntheticMatrixCellSpec,
    config: SyntheticMatrixConfig,
    run_prefix: str,
    workspace_root: Path,
    predictions_root: Path,
    runs_root: Path,
    artifacts_root: Path,
    overwrite: bool,
    validate_workspace: bool,
    skip_index: bool,
    skip_wiki_preparation: bool,
    ingestion_url: str,
    search_service_url: str,
    github_token: str | None,
    stream_worker_logs: bool | None,
    index_poll_interval_seconds: float,
    index_progress_heartbeat_seconds: float,
    index_timeout_seconds: float,
    wiki_poll_interval_seconds: float,
    wiki_progress_heartbeat_seconds: float,
    wiki_timeout_seconds: float,
    region_name: str,
    temperature: float,
    max_tokens: int,
    output_root: Path,
) -> SyntheticMatrixCellResult:
    include_ast_index = _should_include_ast_index(
        context_source=spec.context_source,
        chunking_strategy=spec.chunking_strategy,
    )
    repeat_scores_pct: list[float] = []
    repeat_total_duration_seconds: list[float] = []
    repeat_generation_total_tokens: list[int] = []
    repeat_generation_cost_usd: list[float | None] = []
    run_ids: list[str] = []
    baseline_run_ids: list[str] = []
    for rep in range(1, config.repeat_count + 1):
        matrix_prefix = _matrix_prefix(run_prefix, spec, rep)
        experiment = run_synthetic_experiment(
            family_name=spec.family_name,
            task_count=config.task_count,
            task_type=config.task_type,
            seed=config.seed,
            shared_library_repo_count=config.shared_library_repo_count,
            workspace_root=workspace_root,
            force_workspace=True,
            run_prefix=matrix_prefix,
            predictions_root=predictions_root,
            runs_root=runs_root,
            artifacts_root=artifacts_root,
            overwrite=overwrite,
            validate_workspace=validate_workspace,
            skip_index=skip_index,
            skip_wiki_preparation=skip_wiki_preparation,
            ingestion_url=ingestion_url,
            search_service_url=search_service_url,
            context_source=spec.context_source,
            top_k=config.top_k,
            github_token=github_token,
            stream_worker_logs=stream_worker_logs,
            index_poll_interval_seconds=index_poll_interval_seconds,
            index_progress_heartbeat_seconds=index_progress_heartbeat_seconds,
            index_timeout_seconds=index_timeout_seconds,
            wiki_poll_interval_seconds=wiki_poll_interval_seconds,
            wiki_progress_heartbeat_seconds=wiki_progress_heartbeat_seconds,
            wiki_timeout_seconds=wiki_timeout_seconds,
            model_name=spec.codegen_model,
            region_name=region_name,
            temperature=temperature,
            max_tokens=max_tokens,
            indexing_embedding_strategy=config.embedding_strategy,
            indexing_embedding_model=spec.embedding_model,
            query_embedding_strategy=config.embedding_strategy,
            query_embedding_model=spec.embedding_model,
            include_ast_index=include_ast_index,
        )
        run_ids.append(experiment.lighthouse_summary.run_id)
        baseline_run_ids.append(experiment.baseline_summary.run_id)
        summary = experiment.lighthouse_summary
        score_pct = (
            0.0
            if summary.total_instances == 0
            else (summary.resolved_instances / summary.total_instances) * 100.0
        )
        repeat_scores_pct.append(score_pct)
        repeat_total_duration_seconds.append(experiment.lighthouse_efficiency.total_duration_seconds)
        repeat_generation_total_tokens.append(experiment.lighthouse_efficiency.generation.total_tokens)
        repeat_generation_cost_usd.append(experiment.lighthouse_efficiency.generation.estimated_cost_usd)

    pass_summary = compute_synthetic_pass_at_k(
        run_ids=run_ids,
        k_values=config.k_values,
        runs_root=runs_root,
    )
    pass_table_path = (
        output_root
        / "pass_at_k"
        / f"{_matrix_prefix(run_prefix, spec, 0)}.pass_at_k.txt"
    )
    pass_table_path.parent.mkdir(parents=True, exist_ok=True)
    pass_table_path.write_text(
        render_synthetic_pass_at_k_table(pass_summary) + "\n",
        encoding="utf-8",
    )
    mean_score = sum(repeat_scores_pct) / len(repeat_scores_pct)
    stddev_score = _population_stddev(repeat_scores_pct)
    mean_total_duration_seconds = sum(repeat_total_duration_seconds) / len(repeat_total_duration_seconds)
    mean_generation_total_tokens = sum(repeat_generation_total_tokens) / len(repeat_generation_total_tokens)
    mean_generation_cost_usd = _mean_optional_float(repeat_generation_cost_usd)
    return SyntheticMatrixCellResult(
        spec=spec,
        run_ids=tuple(run_ids),
        baseline_run_ids=tuple(baseline_run_ids),
        repeat_scores_pct=tuple(repeat_scores_pct),
        mean_score_pct=mean_score,
        stddev_score_pct=stddev_score,
        repeat_total_duration_seconds=tuple(repeat_total_duration_seconds),
        mean_total_duration_seconds=mean_total_duration_seconds,
        repeat_generation_total_tokens=tuple(repeat_generation_total_tokens),
        mean_generation_total_tokens=mean_generation_total_tokens,
        repeat_generation_cost_usd=tuple(repeat_generation_cost_usd),
        mean_generation_cost_usd=mean_generation_cost_usd,
        pass_at_k=pass_summary.macro_pass_at_k,
        pass_at_k_table_path=pass_table_path,
        error=None,
    )


def _render_heatmaps(
    rows: Sequence[SyntheticMatrixCellResult],
    config: SyntheticMatrixConfig,
    output_root: Path,
) -> tuple[Path, ...]:
    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        return ()

    try:
        import seaborn as sns  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        sns = None  # type: ignore[assignment]

    grouped: dict[tuple[str, str, str], list[SyntheticMatrixCellResult]] = defaultdict(list)
    for row in rows:
        key = (
            row.spec.family_name,
            row.spec.context_source,
            row.spec.chunking_strategy,
        )
        grouped[key].append(row)

    heatmaps_dir = output_root / "heatmaps"
    heatmaps_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for key, group_rows in grouped.items():
        family_name, context_source, chunking_strategy = key
        score_path = heatmaps_dir / (
            f"{_slug(family_name)}-{_slug(context_source)}-{_slug(chunking_strategy)}-score.png"
        )
        _plot_metric_heatmap(
            plt=plt,
            sns=sns,
            rows=group_rows,
            codegen_models=config.codegen_models,
            embedding_models=config.embedding_models,
            metric_values=lambda row: row.mean_score_pct,
            metric_label="Score (%)",
            title=(
                f"Synthetic score heatmap | family={family_name} | "
                f"search={context_source} | chunking={chunking_strategy}"
            ),
            output_path=score_path,
        )
        generated.append(score_path)
        for k in config.k_values:
            passk_path = heatmaps_dir / (
                f"{_slug(family_name)}-{_slug(context_source)}-"
                f"{_slug(chunking_strategy)}-pass_at_{k}.png"
            )
            _plot_metric_heatmap(
                plt=plt,
                sns=sns,
                rows=group_rows,
                codegen_models=config.codegen_models,
                embedding_models=config.embedding_models,
                metric_values=lambda row, expected_k=k: dict(row.pass_at_k).get(expected_k, math.nan)
                * 100.0,
                metric_label=f"Pass@{k} (%)",
                title=(
                    f"Synthetic pass@{k} heatmap | family={family_name} | "
                    f"search={context_source} | chunking={chunking_strategy}"
                ),
                output_path=passk_path,
            )
            generated.append(passk_path)
    return tuple(generated)


def _plot_metric_heatmap(
    *,
    plt: Any,
    sns: Any,
    rows: Sequence[SyntheticMatrixCellResult],
    codegen_models: Sequence[str],
    embedding_models: Sequence[str],
    metric_values,
    metric_label: str,
    title: str,
    output_path: Path,
) -> None:
    import numpy as np

    matrix = np.full((len(embedding_models), len(codegen_models)), np.nan)
    for row in rows:
        if row.error:
            continue
        try:
            y = embedding_models.index(row.spec.embedding_model)
            x = codegen_models.index(row.spec.codegen_model)
        except ValueError:
            continue
        matrix[y, x] = metric_values(row)

    fig_width = max(8, len(codegen_models) * 1.2)
    fig_height = max(5, len(embedding_models) * 0.8)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    if sns is not None:
        sns.heatmap(
            matrix,
            ax=ax,
            annot=True,
            fmt=".1f",
            cmap="mako",
            linewidths=0.5,
            cbar_kws={"label": metric_label},
            xticklabels=codegen_models,
            yticklabels=embedding_models,
        )
    else:
        heatmap = ax.imshow(matrix, aspect="auto", cmap="viridis")
        fig.colorbar(heatmap, ax=ax, label=metric_label)
        ax.set_xticks(range(len(codegen_models)))
        ax.set_yticks(range(len(embedding_models)))
        ax.set_xticklabels(codegen_models)
        ax.set_yticklabels(embedding_models)
        for row_index in range(matrix.shape[0]):
            for col_index in range(matrix.shape[1]):
                value = matrix[row_index, col_index]
                if math.isnan(value):
                    continue
                ax.text(col_index, row_index, f"{value:.1f}", ha="center", va="center")

    ax.set_xlabel("Codegen model")
    ax.set_ylabel("Embedding model")
    ax.set_title(title)
    plt.xticks(rotation=30, ha="right")
    plt.yticks(rotation=0)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _resolve_families(raw_families: Sequence[str]) -> tuple[str, ...]:
    normalized = [family.strip() for family in raw_families if family.strip()]
    if not normalized:
        raise ValueError("At least one family must be provided.")
    if any(family.lower() == "all" for family in normalized):
        families_root = Path(__file__).parent / "families"
        discovered: list[str] = []
        for child in sorted(families_root.iterdir()):
            if not child.is_dir():
                continue
            if not (child / "family.json").is_file():
                continue
            discovered.append(child.name.replace("_", "-"))
        if not discovered:
            raise ValueError("No synthetic families found.")
        return tuple(discovered)
    for family in normalized:
        load_synthetic_family(family)
    return tuple(normalized)


def _should_include_ast_index(*, context_source: str, chunking_strategy: str) -> bool:
    if chunking_strategy == "ast":
        return True
    if chunking_strategy == "base":
        if context_source == "ast":
            raise ValueError("context_source='ast' requires chunking_strategy='ast'.")
        return context_source == "combined"
    raise ValueError(f"Unsupported chunking strategy: {chunking_strategy!r}")


def _matrix_run_id(
    run_prefix: str,
    spec: SyntheticMatrixCellSpec,
    repeat_index: int,
    *,
    retrieval: bool,
) -> str:
    prefix = _matrix_prefix(run_prefix, spec, repeat_index)
    return f"{prefix}-{'{}'.format(spec.context_source if retrieval else 'baseline')}"


def _matrix_prefix(run_prefix: str, spec: SyntheticMatrixCellSpec, repeat_index: int) -> str:
    return (
        f"{_slug(run_prefix)}"
        f"-fam-{_slug(spec.family_name)}"
        f"-ctx-{_slug(spec.context_source)}"
        f"-chunk-{_slug(spec.chunking_strategy)}"
        f"-cg-{_slug(spec.codegen_model)}"
        f"-em-{_slug(spec.embedding_model)}"
        f"-r{repeat_index:02d}"
    )


def _slug(value: str) -> str:
    compact = _SAFE_SLUG_RE.sub("-", value.lower()).strip("-")
    return compact or "x"


def _population_stddev(values: Sequence[float]) -> float:
    if not values:
        return math.nan
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def _mean_optional_float(values: Sequence[float | None]) -> float | None:
    observed = [value for value in values if value is not None]
    if not observed:
        return None
    return sum(observed) / len(observed)


def _as_non_empty_str_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty list.")
    normalized = tuple(str(item).strip() for item in value if str(item).strip())
    if not normalized:
        raise ValueError(f"{field_name} must include at least one non-empty value.")
    return normalized


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _render_table(headers: tuple[str, ...], rows: Iterable[Sequence[str]]) -> str:
    widths = [len(header) for header in headers]
    normalized_rows = list(rows)
    for row in normalized_rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def _fmt(row: Sequence[str]) -> str:
        return " | ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))

    separator = "-+-".join("-" * width for width in widths)
    lines = [_fmt(headers), separator]
    lines.extend(_fmt(row) for row in normalized_rows)
    return "\n".join(lines)
