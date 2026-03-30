from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from eval.bedrock import (
    DEFAULT_BASELINE_MODEL,
    DEFAULT_BASELINE_REGION,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    BedrockPatchGenerator,
)
from eval.lighthouse import DEFAULT_SEARCH_TOP_K
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
) -> SyntheticExperimentResult:
    if not run_prefix.strip():
        raise ValueError("run_prefix must not be empty.")
    if context_source not in {"code", "wiki", "ast", "combined", "code+wiki"}:
        raise ValueError(
            "context_source must be 'code', 'wiki', 'ast', 'combined', or 'code+wiki'."
        )

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

    if not skip_index:
        index_synthetic_repository(
            workspace=workspace,
            ingestion_url=ingestion_url,
            github_token=github_token,
            stream_worker_logs=stream_worker_logs,
            poll_interval_seconds=index_poll_interval_seconds,
            progress_heartbeat_seconds=index_progress_heartbeat_seconds,
            timeout_seconds=index_timeout_seconds,
            include_ast=context_source in {"ast", "combined"},
        )
    if not skip_wiki_preparation:
        prepare_synthetic_wiki(
            workspace=workspace,
            ingestion_url=ingestion_url,
            poll_interval_seconds=wiki_poll_interval_seconds,
            progress_heartbeat_seconds=wiki_progress_heartbeat_seconds,
            timeout_seconds=wiki_timeout_seconds,
        )

    predictions_root = predictions_root.resolve()
    baseline_predictions_path = predictions_root / f"{run_prefix}-baseline.jsonl"
    lighthouse_predictions_path = (
        predictions_root / f"{run_prefix}-{context_source}.jsonl"
    )
    baseline_run_id = f"{run_prefix}-baseline"
    lighthouse_run_id = f"{run_prefix}-{context_source}"

    baseline_generator = BedrockPatchGenerator(
        model_name=model_name,
        region_name=region_name,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    generate_synthetic_baseline_predictions(
        tasks=workspace.tasks,
        generator=baseline_generator,
        output_path=baseline_predictions_path,
        overwrite=overwrite,
    )

    lighthouse_messages = build_synthetic_lighthouse_messages(
        workspace=workspace,
        search_service_url=search_service_url,
        top_k=top_k,
        context_source=context_source,
    )
    lighthouse_generator = BedrockPatchGenerator(
        model_name=model_name,
        region_name=region_name,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    generate_synthetic_predictions(
        tasks=workspace.tasks,
        generator=lighthouse_generator,
        output_path=lighthouse_predictions_path,
        overwrite=overwrite,
        context_source=context_source,
        build_user_message=lambda prepared: lighthouse_messages[prepared.task.task_id],
        progress_label="Generating synthetic Lighthouse patch for",
    )

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
) -> SyntheticExperimentSuiteResult:
    if not run_prefix.strip():
        raise ValueError("run_prefix must not be empty.")

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

    if not skip_index:
        index_synthetic_repository(
            workspace=workspace,
            ingestion_url=ingestion_url,
            github_token=github_token,
            stream_worker_logs=stream_worker_logs,
            poll_interval_seconds=index_poll_interval_seconds,
            progress_heartbeat_seconds=index_progress_heartbeat_seconds,
            timeout_seconds=index_timeout_seconds,
            include_ast=True,
        )
    if not skip_wiki_preparation:
        prepare_synthetic_wiki(
            workspace=workspace,
            ingestion_url=ingestion_url,
            poll_interval_seconds=wiki_poll_interval_seconds,
            progress_heartbeat_seconds=wiki_progress_heartbeat_seconds,
            timeout_seconds=wiki_timeout_seconds,
        )

    predictions_root = predictions_root.resolve()
    baseline_predictions_path = predictions_root / f"{run_prefix}-baseline.jsonl"
    baseline_run_id = f"{run_prefix}-baseline"

    baseline_generator = BedrockPatchGenerator(
        model_name=model_name,
        region_name=region_name,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    generate_synthetic_baseline_predictions(
        tasks=workspace.tasks,
        generator=baseline_generator,
        output_path=baseline_predictions_path,
        overwrite=overwrite,
    )

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

    for context_source in ("code", "wiki", "ast", "combined"):
        lighthouse_predictions_path = (
            predictions_root / f"{run_prefix}-{context_source}.jsonl"
        )
        lighthouse_run_id = f"{run_prefix}-{context_source}"

        lighthouse_messages = build_synthetic_lighthouse_messages(
            workspace=workspace,
            search_service_url=search_service_url,
            top_k=top_k,
            context_source=context_source,
        )
        lighthouse_generator = BedrockPatchGenerator(
            model_name=model_name,
            region_name=region_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
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
                "lighthouse_experiments": {
                    label: summary.experiment.to_json()
                    for label, summary in lighthouse_summaries.items()
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
    }
