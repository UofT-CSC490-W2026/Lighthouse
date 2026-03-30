from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from eval.bedrock import (
    DEFAULT_BASELINE_MODEL,
    DEFAULT_BASELINE_REGION,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    BedrockPatchGenerator,
)
from eval.generator import PatchGenerator
from eval.efficiency import RunEfficiencySummary
from eval.lighthouse import DEFAULT_SEARCH_TOP_K
from eval.openai import OpenAIPatchGenerator
from .compare import (
    SyntheticRunComparison,
    SyntheticScoreRow,
    build_synthetic_score_rows,
    compare_synthetic_runs,
    render_synthetic_comparison_tables,
    render_synthetic_score_table,
)
from .eval import (
    SyntheticRunSummary,
    evaluate_synthetic_predictions,
    validate_prepared_synthetic_workspace,
)
from .lighthouse import (
    build_synthetic_lighthouse_messages,
    index_synthetic_repository,
    prepare_synthetic_wiki,
)
from .metadata import resolve_synthetic_experiment_metadata
from .predictions import (
    generate_synthetic_baseline_predictions,
    generate_synthetic_predictions,
)
from .workspace import (
    DEFAULT_SYNTHETIC_RUNS_ROOT,
    DEFAULT_SYNTHETIC_WORKSPACE_ROOT,
    PreparedSyntheticWorkspace,
    prepare_synthetic_workspace,
)

DEFAULT_SYNTHETIC_PREDICTIONS_ROOT = Path(".cache/eval/runs")
DEFAULT_SYNTHETIC_EXPERIMENT_ARTIFACTS_ROOT = Path(".cache/eval/synthetic_experiments")


@dataclass(frozen=True)
class SyntheticExperimentResult:
    workspace: PreparedSyntheticWorkspace
    run_prefix: str
    baseline_predictions_path: Path
    lighthouse_predictions_path: Path
    baseline_summary: SyntheticRunSummary
    lighthouse_summary: SyntheticRunSummary
    comparison: SyntheticRunComparison
    comparison_text_path: Path
    comparison_json_path: Path
    report_path: Path
    baseline_efficiency: RunEfficiencySummary
    lighthouse_efficiency: RunEfficiencySummary


@dataclass(frozen=True)
class SyntheticExperimentSuiteResult:
    workspace: PreparedSyntheticWorkspace
    run_prefix: str
    baseline_predictions_path: Path
    lighthouse_predictions_paths: dict[str, Path]
    baseline_summary: SyntheticRunSummary
    lighthouse_summaries: dict[str, SyntheticRunSummary]
    comparisons: dict[str, SyntheticRunComparison]
    score_rows: tuple[SyntheticScoreRow, ...]
    score_text_path: Path
    score_json_path: Path
    comparison_text_paths: dict[str, Path]
    comparison_json_paths: dict[str, Path]
    report_path: Path
    baseline_efficiency: RunEfficiencySummary
    lighthouse_efficiencies: dict[str, RunEfficiencySummary]


def run_synthetic_experiment(
    *,
    family_name: str,
    task_count: int | None,
    task_type: str | None,
    seed: int | None,
    shared_library_repo_count: int | None,
    workspace_root: Path = DEFAULT_SYNTHETIC_WORKSPACE_ROOT,
    force_workspace: bool = False,
    run_prefix: str,
    predictions_root: Path = DEFAULT_SYNTHETIC_PREDICTIONS_ROOT,
    runs_root: Path = DEFAULT_SYNTHETIC_RUNS_ROOT,
    artifacts_root: Path = DEFAULT_SYNTHETIC_EXPERIMENT_ARTIFACTS_ROOT,
    overwrite: bool = False,
    validate_workspace: bool = True,
    skip_index: bool = False,
    skip_wiki_preparation: bool = False,
    ingestion_url: str,
    search_service_url: str,
    context_source: str,
    top_k: int = DEFAULT_SEARCH_TOP_K,
    github_token: str | None = None,
    stream_worker_logs: bool | None = None,
    index_poll_interval_seconds: float,
    index_progress_heartbeat_seconds: float,
    index_timeout_seconds: float,
    wiki_poll_interval_seconds: float,
    wiki_progress_heartbeat_seconds: float,
    wiki_timeout_seconds: float,
    model_name: str = DEFAULT_BASELINE_MODEL,
    region_name: str = DEFAULT_BASELINE_REGION,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    indexing_embedding_strategy: str | None = None,
    indexing_embedding_model: str | None = None,
    query_embedding_strategy: str | None = None,
    query_embedding_model: str | None = None,
    include_ast_index: bool | None = None,
) -> SyntheticExperimentResult:
    if not run_prefix.strip():
        raise ValueError("run_prefix must not be empty.")
    if context_source not in {"code", "wiki", "ast", "combined", "code+wiki", "grep"}:
        raise ValueError(
            "context_source must be 'code', 'wiki', 'ast', 'combined', 'code+wiki', or 'grep'."
        )

    resolved_include_ast = (
        context_source in {"ast", "combined"}
        if include_ast_index is None
        else include_ast_index
    )
    if context_source == "ast" and not resolved_include_ast:
        raise ValueError("context_source='ast' requires include_ast_index=True.")

    workspace = prepare_synthetic_workspace(
        family_name=family_name,
        task_count=task_count,
        task_type=task_type,
        seed=seed,
        shared_library_repo_count=shared_library_repo_count,
        workspace_root=workspace_root,
        force=force_workspace,
    )

    if validate_workspace and (
        force_workspace or not workspace.validation_report_path.is_file()
    ):
        validate_prepared_synthetic_workspace(workspace)

    indexing_duration_seconds = 0.0
    should_run_index = not skip_index and context_source != "grep"
    if should_run_index:
        indexing_started = perf_counter()
        index_synthetic_repository(
            workspace=workspace,
            ingestion_url=ingestion_url,
            github_token=github_token,
            stream_worker_logs=stream_worker_logs,
            poll_interval_seconds=index_poll_interval_seconds,
            progress_heartbeat_seconds=index_progress_heartbeat_seconds,
            timeout_seconds=index_timeout_seconds,
            include_ast=resolved_include_ast,
            embedding_strategy=indexing_embedding_strategy,
            embedding_model=indexing_embedding_model,
        )
        indexing_duration_seconds = perf_counter() - indexing_started
    wiki_duration_seconds = 0.0
    should_run_wiki = not skip_wiki_preparation and context_source != "grep"
    if should_run_wiki:
        wiki_started = perf_counter()
        prepare_synthetic_wiki(
            workspace=workspace,
            ingestion_url=ingestion_url,
            poll_interval_seconds=wiki_poll_interval_seconds,
            progress_heartbeat_seconds=wiki_progress_heartbeat_seconds,
            timeout_seconds=wiki_timeout_seconds,
            embedding_strategy=indexing_embedding_strategy,
            embedding_model=indexing_embedding_model,
        )
        wiki_duration_seconds = perf_counter() - wiki_started

    predictions_root = predictions_root.resolve()
    baseline_predictions_path = predictions_root / f"{run_prefix}-baseline.jsonl"
    lighthouse_predictions_path = (
        predictions_root / f"{run_prefix}-{context_source}.jsonl"
    )
    baseline_run_id = f"{run_prefix}-baseline"
    lighthouse_run_id = f"{run_prefix}-{context_source}"

    baseline_generator = _build_patch_generator(
        model_name=model_name,
        region_name=region_name,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    baseline_generation_started = perf_counter()
    generate_synthetic_baseline_predictions(
        tasks=workspace.tasks,
        generator=baseline_generator,
        output_path=baseline_predictions_path,
        overwrite=overwrite,
    )
    baseline_generation_duration_seconds = perf_counter() - baseline_generation_started

    retrieval_started = perf_counter()
    lighthouse_messages = build_synthetic_lighthouse_messages(
        workspace=workspace,
        search_service_url=search_service_url,
        top_k=top_k,
        context_source=context_source,
        query_embedding_strategy=query_embedding_strategy,
        query_embedding_model=query_embedding_model,
    )
    retrieval_duration_seconds = perf_counter() - retrieval_started
    lighthouse_generator = _build_patch_generator(
        model_name=model_name,
        region_name=region_name,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    lighthouse_generation_started = perf_counter()
    generate_synthetic_predictions(
        tasks=workspace.tasks,
        generator=lighthouse_generator,
        output_path=lighthouse_predictions_path,
        overwrite=overwrite,
        context_source=context_source,
        build_user_message=lambda prepared: lighthouse_messages[prepared.task.task_id],
        progress_label="Generating synthetic Lighthouse patch for",
    )
    lighthouse_generation_duration_seconds = perf_counter() - lighthouse_generation_started

    baseline_experiment = resolve_synthetic_experiment_metadata(
        generation_model_name_or_path=model_name,
        generation_region_name=region_name,
        context_source="baseline",
        search_top_k=None,
        indexing_embedding_strategy=indexing_embedding_strategy,
        indexing_embedding_model=indexing_embedding_model,
        query_embedding_strategy=query_embedding_strategy,
        query_embedding_model=query_embedding_model,
        repo_root=Path.cwd(),
    )
    lighthouse_experiment = resolve_synthetic_experiment_metadata(
        generation_model_name_or_path=model_name,
        generation_region_name=region_name,
        context_source=context_source,
        search_top_k=top_k,
        indexing_embedding_strategy=indexing_embedding_strategy,
        indexing_embedding_model=indexing_embedding_model,
        query_embedding_strategy=query_embedding_strategy,
        query_embedding_model=query_embedding_model,
        repo_root=Path.cwd(),
    )

    baseline_summary = evaluate_synthetic_predictions(
        workspace=workspace,
        predictions_path=baseline_predictions_path,
        run_id=baseline_run_id,
        runs_root=runs_root,
        overwrite=overwrite,
        experiment=baseline_experiment,
    )
    lighthouse_summary = evaluate_synthetic_predictions(
        workspace=workspace,
        predictions_path=lighthouse_predictions_path,
        run_id=lighthouse_run_id,
        runs_root=runs_root,
        overwrite=overwrite,
        experiment=lighthouse_experiment,
    )

    comparison = compare_synthetic_runs(
        baseline_run_id=baseline_run_id,
        lighthouse_run_id=lighthouse_run_id,
        runs_root=runs_root,
        baseline_label="baseline",
        lighthouse_label=context_source,
    )

    artifacts_root = artifacts_root.resolve()
    artifacts_root.mkdir(parents=True, exist_ok=True)
    comparison_text_path = artifacts_root / f"{run_prefix}.comparison.txt"
    comparison_json_path = artifacts_root / f"{run_prefix}.comparison.json"
    report_path = artifacts_root / f"{run_prefix}.experiment.json"

    baseline_efficiency = _merge_run_efficiency(
        summary=baseline_summary,
        indexing_duration_seconds=0.0,
        wiki_duration_seconds=0.0,
        retrieval_duration_seconds=0.0,
        generation_duration_seconds=baseline_generation_duration_seconds,
        retrieval_request_count=0,
    )
    lighthouse_efficiency = _merge_run_efficiency(
        summary=lighthouse_summary,
        indexing_duration_seconds=indexing_duration_seconds,
        wiki_duration_seconds=wiki_duration_seconds,
        retrieval_duration_seconds=retrieval_duration_seconds,
        generation_duration_seconds=lighthouse_generation_duration_seconds,
        retrieval_request_count=len(workspace.tasks),
    )
    comparison_text = render_synthetic_comparison_tables(comparison)
    comparison_text_path.write_text(comparison_text + "\n", encoding="utf-8")
    comparison_json_path.write_text(
        json.dumps(_comparison_to_json(comparison), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "run_prefix": run_prefix,
                "family_name": workspace.family.config.family_name,
                "family_version": workspace.family.config.family_version,
                "workspace_dir": str(workspace.workspace_dir.resolve()),
                "validation_report_path": str(
                    workspace.validation_report_path.resolve()
                ),
                "baseline_predictions_path": str(baseline_predictions_path.resolve()),
                "lighthouse_predictions_path": str(
                    lighthouse_predictions_path.resolve()
                ),
                "baseline_run_id": baseline_summary.run_id,
                "lighthouse_run_id": lighthouse_summary.run_id,
                "context_source": context_source,
                "comparison_text_path": str(comparison_text_path.resolve()),
                "comparison_json_path": str(comparison_json_path.resolve()),
                "baseline_experiment": baseline_summary.experiment.to_json(),
                "lighthouse_experiment": lighthouse_summary.experiment.to_json(),
                "baseline_efficiency": baseline_efficiency.to_json(),
                "lighthouse_efficiency": lighthouse_efficiency.to_json(),
                "comparison": _comparison_to_json(comparison),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return SyntheticExperimentResult(
        workspace=workspace,
        run_prefix=run_prefix,
        baseline_predictions_path=baseline_predictions_path,
        lighthouse_predictions_path=lighthouse_predictions_path,
        baseline_summary=baseline_summary,
        lighthouse_summary=lighthouse_summary,
        comparison=comparison,
        comparison_text_path=comparison_text_path,
        comparison_json_path=comparison_json_path,
        report_path=report_path,
        baseline_efficiency=baseline_efficiency,
        lighthouse_efficiency=lighthouse_efficiency,
    )


def run_synthetic_experiment_suite(
    *,
    family_name: str,
    task_count: int | None,
    task_type: str | None,
    seed: int | None,
    shared_library_repo_count: int | None,
    workspace_root: Path = DEFAULT_SYNTHETIC_WORKSPACE_ROOT,
    force_workspace: bool = False,
    run_prefix: str,
    predictions_root: Path = DEFAULT_SYNTHETIC_PREDICTIONS_ROOT,
    runs_root: Path = DEFAULT_SYNTHETIC_RUNS_ROOT,
    artifacts_root: Path = DEFAULT_SYNTHETIC_EXPERIMENT_ARTIFACTS_ROOT,
    overwrite: bool = False,
    validate_workspace: bool = True,
    skip_index: bool = False,
    skip_wiki_preparation: bool = False,
    ingestion_url: str,
    search_service_url: str,
    top_k: int = DEFAULT_SEARCH_TOP_K,
    github_token: str | None = None,
    stream_worker_logs: bool | None = None,
    index_poll_interval_seconds: float,
    index_progress_heartbeat_seconds: float,
    index_timeout_seconds: float,
    wiki_poll_interval_seconds: float,
    wiki_progress_heartbeat_seconds: float,
    wiki_timeout_seconds: float,
    model_name: str = DEFAULT_BASELINE_MODEL,
    region_name: str = DEFAULT_BASELINE_REGION,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    indexing_embedding_strategy: str | None = None,
    indexing_embedding_model: str | None = None,
    query_embedding_strategy: str | None = None,
    query_embedding_model: str | None = None,
    include_ast_index: bool | None = None,
) -> SyntheticExperimentSuiteResult:
    if not run_prefix.strip():
        raise ValueError("run_prefix must not be empty.")

    resolved_include_ast = True if include_ast_index is None else include_ast_index

    workspace = prepare_synthetic_workspace(
        family_name=family_name,
        task_count=task_count,
        task_type=task_type,
        seed=seed,
        shared_library_repo_count=shared_library_repo_count,
        workspace_root=workspace_root,
        force=force_workspace,
    )

    if validate_workspace and (
        force_workspace or not workspace.validation_report_path.is_file()
    ):
        validate_prepared_synthetic_workspace(workspace)

    indexing_duration_seconds = 0.0
    if not skip_index:
        indexing_started = perf_counter()
        index_synthetic_repository(
            workspace=workspace,
            ingestion_url=ingestion_url,
            github_token=github_token,
            stream_worker_logs=stream_worker_logs,
            poll_interval_seconds=index_poll_interval_seconds,
            progress_heartbeat_seconds=index_progress_heartbeat_seconds,
            timeout_seconds=index_timeout_seconds,
            include_ast=resolved_include_ast,
            embedding_strategy=indexing_embedding_strategy,
            embedding_model=indexing_embedding_model,
        )
        indexing_duration_seconds = perf_counter() - indexing_started
    wiki_duration_seconds = 0.0
    if not skip_wiki_preparation:
        wiki_started = perf_counter()
        prepare_synthetic_wiki(
            workspace=workspace,
            ingestion_url=ingestion_url,
            poll_interval_seconds=wiki_poll_interval_seconds,
            progress_heartbeat_seconds=wiki_progress_heartbeat_seconds,
            timeout_seconds=wiki_timeout_seconds,
            embedding_strategy=indexing_embedding_strategy,
            embedding_model=indexing_embedding_model,
        )
        wiki_duration_seconds = perf_counter() - wiki_started

    predictions_root = predictions_root.resolve()
    baseline_predictions_path = predictions_root / f"{run_prefix}-baseline.jsonl"
    baseline_run_id = f"{run_prefix}-baseline"

    baseline_generator = _build_patch_generator(
        model_name=model_name,
        region_name=region_name,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    baseline_generation_started = perf_counter()
    generate_synthetic_baseline_predictions(
        tasks=workspace.tasks,
        generator=baseline_generator,
        output_path=baseline_predictions_path,
        overwrite=overwrite,
    )
    baseline_generation_duration_seconds = perf_counter() - baseline_generation_started

    baseline_experiment = resolve_synthetic_experiment_metadata(
        generation_model_name_or_path=model_name,
        generation_region_name=region_name,
        context_source="baseline",
        search_top_k=None,
        indexing_embedding_strategy=indexing_embedding_strategy,
        indexing_embedding_model=indexing_embedding_model,
        query_embedding_strategy=query_embedding_strategy,
        query_embedding_model=query_embedding_model,
        repo_root=Path.cwd(),
    )
    baseline_summary = evaluate_synthetic_predictions(
        workspace=workspace,
        predictions_path=baseline_predictions_path,
        run_id=baseline_run_id,
        runs_root=runs_root,
        overwrite=overwrite,
        experiment=baseline_experiment,
    )

    lighthouse_predictions_paths: dict[str, Path] = {}
    lighthouse_summaries: dict[str, SyntheticRunSummary] = {}
    comparisons: dict[str, SyntheticRunComparison] = {}
    lighthouse_efficiencies: dict[str, RunEfficiencySummary] = {}

    for context_source in ("code", "wiki", "ast", "combined", "grep"):
        lighthouse_predictions_path = (
            predictions_root / f"{run_prefix}-{context_source}.jsonl"
        )
        lighthouse_run_id = f"{run_prefix}-{context_source}"

        retrieval_started = perf_counter()
        lighthouse_messages = build_synthetic_lighthouse_messages(
            workspace=workspace,
            search_service_url=search_service_url,
            top_k=top_k,
            context_source=context_source,
            query_embedding_strategy=query_embedding_strategy,
            query_embedding_model=query_embedding_model,
        )
        retrieval_duration_seconds = perf_counter() - retrieval_started
        lighthouse_generator = _build_patch_generator(
            model_name=model_name,
            region_name=region_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        generation_started = perf_counter()
        generate_synthetic_predictions(
            tasks=workspace.tasks,
            generator=lighthouse_generator,
            output_path=lighthouse_predictions_path,
            overwrite=overwrite,
            context_source=context_source,
            build_user_message=lambda prepared, messages=lighthouse_messages: messages[
                prepared.task.task_id
            ],
            progress_label="Generating synthetic Lighthouse patch for",
        )
        generation_duration_seconds = perf_counter() - generation_started

        lighthouse_experiment = resolve_synthetic_experiment_metadata(
            generation_model_name_or_path=model_name,
            generation_region_name=region_name,
            context_source=context_source,
            search_top_k=top_k,
            indexing_embedding_strategy=indexing_embedding_strategy,
            indexing_embedding_model=indexing_embedding_model,
            query_embedding_strategy=query_embedding_strategy,
            query_embedding_model=query_embedding_model,
            repo_root=Path.cwd(),
        )
        lighthouse_summary = evaluate_synthetic_predictions(
            workspace=workspace,
            predictions_path=lighthouse_predictions_path,
            run_id=lighthouse_run_id,
            runs_root=runs_root,
            overwrite=overwrite,
            experiment=lighthouse_experiment,
        )
        comparison = compare_synthetic_runs(
            baseline_run_id=baseline_run_id,
            lighthouse_run_id=lighthouse_run_id,
            runs_root=runs_root,
            baseline_label="baseline",
            lighthouse_label=context_source,
        )

        lighthouse_predictions_paths[context_source] = lighthouse_predictions_path
        lighthouse_summaries[context_source] = lighthouse_summary
        comparisons[context_source] = comparison
        lighthouse_efficiencies[context_source] = _merge_run_efficiency(
            summary=lighthouse_summary,
            indexing_duration_seconds=indexing_duration_seconds,
            wiki_duration_seconds=wiki_duration_seconds,
            retrieval_duration_seconds=retrieval_duration_seconds,
            generation_duration_seconds=generation_duration_seconds,
            retrieval_request_count=len(workspace.tasks),
        )

    score_rows = build_synthetic_score_rows(
        baseline=baseline_summary,
        retrieval_runs=lighthouse_summaries,
    )

    artifacts_root = artifacts_root.resolve()
    artifacts_root.mkdir(parents=True, exist_ok=True)
    score_text_path = artifacts_root / f"{run_prefix}.score.txt"
    score_json_path = artifacts_root / f"{run_prefix}.score.json"
    comparison_text_paths: dict[str, Path] = {}
    comparison_json_paths: dict[str, Path] = {}

    score_text = render_synthetic_score_table(score_rows)
    score_text_path.write_text(score_text + "\n", encoding="utf-8")
    score_json_path.write_text(
        json.dumps(
            [
                {
                    "label": row.label,
                    "run_id": row.run_id,
                    "resolved_instances": row.resolved_instances,
                    "total_instances": row.total_instances,
                    "unresolved_instances": row.unresolved_instances,
                    "score_pct": row.score_pct,
                }
                for row in score_rows
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    for context_source, comparison in comparisons.items():
        comparison_text_path = (
            artifacts_root / f"{run_prefix}.{context_source}.comparison.txt"
        )
        comparison_json_path = (
            artifacts_root / f"{run_prefix}.{context_source}.comparison.json"
        )
        comparison_text_paths[context_source] = comparison_text_path
        comparison_json_paths[context_source] = comparison_json_path
        comparison_text_path.write_text(
            render_synthetic_comparison_tables(comparison) + "\n",
            encoding="utf-8",
        )
        comparison_json_path.write_text(
            json.dumps(_comparison_to_json(comparison), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

    report_path = artifacts_root / f"{run_prefix}.experiment.json"
    baseline_efficiency = _merge_run_efficiency(
        summary=baseline_summary,
        indexing_duration_seconds=0.0,
        wiki_duration_seconds=0.0,
        retrieval_duration_seconds=0.0,
        generation_duration_seconds=baseline_generation_duration_seconds,
        retrieval_request_count=0,
    )
    report_path.write_text(
        json.dumps(
            {
                "run_prefix": run_prefix,
                "family_name": workspace.family.config.family_name,
                "family_version": workspace.family.config.family_version,
                "workspace_dir": str(workspace.workspace_dir.resolve()),
                "validation_report_path": str(
                    workspace.validation_report_path.resolve()
                ),
                "baseline_predictions_path": str(baseline_predictions_path.resolve()),
                "baseline_run_id": baseline_summary.run_id,
                "lighthouse_predictions_paths": {
                    label: str(path.resolve())
                    for label, path in lighthouse_predictions_paths.items()
                },
                "lighthouse_run_ids": {
                    label: summary.run_id
                    for label, summary in lighthouse_summaries.items()
                },
                "score_text_path": str(score_text_path.resolve()),
                "score_json_path": str(score_json_path.resolve()),
                "comparison_text_paths": {
                    label: str(path.resolve())
                    for label, path in comparison_text_paths.items()
                },
                "comparison_json_paths": {
                    label: str(path.resolve())
                    for label, path in comparison_json_paths.items()
                },
                "baseline_experiment": baseline_summary.experiment.to_json(),
                "baseline_efficiency": baseline_efficiency.to_json(),
                "lighthouse_experiments": {
                    label: summary.experiment.to_json()
                    for label, summary in lighthouse_summaries.items()
                },
                "lighthouse_efficiencies": {
                    label: summary.to_json()
                    for label, summary in lighthouse_efficiencies.items()
                },
                "scores": [
                    {
                        "label": row.label,
                        "run_id": row.run_id,
                        "resolved_instances": row.resolved_instances,
                        "total_instances": row.total_instances,
                        "unresolved_instances": row.unresolved_instances,
                        "score_pct": row.score_pct,
                    }
                    for row in score_rows
                ],
                "comparisons": {
                    label: _comparison_to_json(comparison)
                    for label, comparison in comparisons.items()
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return SyntheticExperimentSuiteResult(
        workspace=workspace,
        run_prefix=run_prefix,
        baseline_predictions_path=baseline_predictions_path,
        lighthouse_predictions_paths=lighthouse_predictions_paths,
        baseline_summary=baseline_summary,
        lighthouse_summaries=lighthouse_summaries,
        comparisons=comparisons,
        score_rows=score_rows,
        score_text_path=score_text_path,
        score_json_path=score_json_path,
        comparison_text_paths=comparison_text_paths,
        comparison_json_paths=comparison_json_paths,
        report_path=report_path,
        baseline_efficiency=baseline_efficiency,
        lighthouse_efficiencies=lighthouse_efficiencies,
    )


def _comparison_to_json(comparison: SyntheticRunComparison) -> dict[str, object]:
    return {
        "baseline_label": comparison.baseline_label,
        "lighthouse_label": comparison.lighthouse_label,
        "baseline_run_id": comparison.baseline.run_id,
        "lighthouse_run_id": comparison.lighthouse.run_id,
        "improved_tasks": comparison.improved_tasks,
        "regressed_tasks": comparison.regressed_tasks,
        "unchanged_tasks": comparison.unchanged_tasks,
        "baseline": _summary_to_json(comparison.baseline),
        "lighthouse": _summary_to_json(comparison.lighthouse),
        "task_comparisons": [
            {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "baseline_status": task.baseline_status,
                "lighthouse_status": task.lighthouse_status,
                "baseline_context_source": task.baseline_context_source,
                "lighthouse_context_source": task.lighthouse_context_source,
                "baseline_failing_tests": task.baseline_failing_tests,
                "lighthouse_failing_tests": task.lighthouse_failing_tests,
                "delta": task.delta,
            }
            for task in comparison.task_comparisons
        ],
    }


def _summary_to_json(summary: SyntheticRunSummary) -> dict[str, object]:
    return {
        "run_id": summary.run_id,
        "family_name": summary.family_name,
        "family_version": summary.family_version,
        "predictions_path": str(summary.predictions_path.resolve()),
        "run_dir": str(summary.run_dir.resolve()),
        "experiment": summary.experiment.to_json(),
        "total_instances": summary.total_instances,
        "submitted_instances": summary.submitted_instances,
        "completed_instances": summary.completed_instances,
        "resolved_instances": summary.resolved_instances,
        "unresolved_instances": summary.unresolved_instances,
        "empty_patch_instances": summary.empty_patch_instances,
        "error_instances": summary.error_instances,
        "efficiency": summary.efficiency.to_json() if summary.efficiency is not None else None,
    }


def _build_patch_generator(
    *,
    model_name: str,
    region_name: str,
    temperature: float,
    max_tokens: int,
) -> PatchGenerator:
    if model_name.lower().startswith("openai/"):
        return OpenAIPatchGenerator(
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    return BedrockPatchGenerator(
        model_name=model_name,
        region_name=region_name,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _merge_run_efficiency(
    *,
    summary: SyntheticRunSummary,
    indexing_duration_seconds: float,
    wiki_duration_seconds: float,
    retrieval_duration_seconds: float,
    generation_duration_seconds: float,
    retrieval_request_count: int,
) -> RunEfficiencySummary:
    base = summary.efficiency
    if base is None:
        raise ValueError("Synthetic summary is missing efficiency metrics.")
    total_duration_seconds = (
        indexing_duration_seconds
        + wiki_duration_seconds
        + retrieval_duration_seconds
        + generation_duration_seconds
    )
    return RunEfficiencySummary(
        generation=base.generation,
        indexing_duration_seconds=indexing_duration_seconds,
        wiki_duration_seconds=wiki_duration_seconds,
        retrieval_duration_seconds=retrieval_duration_seconds,
        generation_duration_seconds=generation_duration_seconds,
        total_duration_seconds=total_duration_seconds,
        retrieval_request_count=retrieval_request_count,
        retrieval_query_tokens_estimate=base.retrieval_query_tokens_estimate,
        retrieval_query_cost_estimate_usd=base.retrieval_query_cost_estimate_usd,
    )
