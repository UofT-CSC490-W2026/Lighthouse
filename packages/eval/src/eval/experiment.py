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
from eval.compare import (
    SWEBenchRunComparison,
    SWEBenchScoreRow,
    build_swebench_score_rows,
    compare_swebench_runs,
    render_swebench_comparison_tables,
    render_swebench_score_table,
)
from eval.harness import (
    DEFAULT_CACHE_LEVEL,
    DEFAULT_HARNESS_WORKDIR,
    DEFAULT_RUN_TIMEOUT_SECONDS,
    evaluate_swebench_predictions,
    prepare_swebench_images,
)
from eval.indexing import (
    DEFAULT_INGESTION_URL,
    DEFAULT_PROGRESS_HEARTBEAT_SECONDS,
    DEFAULT_REPO_REGISTRY_OUTPUT,
    DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
    DEFAULT_STATUS_TIMEOUT_SECONDS,
    index_swebench_repositories,
)
from eval.lighthouse import (
    DEFAULT_LIGHTHOUSE_BRANCH,
    DEFAULT_SEARCH_SERVICE_URL,
    DEFAULT_SEARCH_TOP_K,
    build_lighthouse_messages,
)
from eval.predictions import generate_baseline_predictions, generate_predictions
from eval.prompts import build_baseline_user_message
from eval.slice import (
    DEFAULT_DATASET_NAME,
    DEFAULT_SPLIT,
    SWEBenchTask,
    load_swebench_slice,
)
from eval.summary import HarnessRunSummary, summarize_swebench_run
from eval.wiki import (
    DEFAULT_WIKI_INGESTION_URL,
    DEFAULT_WIKI_POLL_INTERVAL_SECONDS,
    DEFAULT_WIKI_PROGRESS_HEARTBEAT_SECONDS,
    DEFAULT_WIKI_TIMEOUT_SECONDS,
    build_wiki_lighthouse_messages,
    prepare_lighthouse_wiki,
)

DEFAULT_SWEBENCH_PREDICTIONS_ROOT = Path(".cache/eval/swebench_predictions")
DEFAULT_SWEBENCH_EXPERIMENT_ARTIFACTS_ROOT = Path(".cache/eval/swebench_experiments")


@dataclass(frozen=True)
class SWEBenchExperimentResult:
    tasks: tuple[SWEBenchTask, ...]
    run_prefix: str
    baseline_predictions_path: Path
    lighthouse_predictions_path: Path
    baseline_summary: HarnessRunSummary
    lighthouse_summary: HarnessRunSummary
    comparison: SWEBenchRunComparison
    comparison_text_path: Path
    comparison_json_path: Path
    report_path: Path


@dataclass(frozen=True)
class SWEBenchExperimentSuiteResult:
    tasks: tuple[SWEBenchTask, ...]
    run_prefix: str
    baseline_predictions_path: Path
    lighthouse_predictions_paths: dict[str, Path]
    baseline_summary: HarnessRunSummary
    lighthouse_summaries: dict[str, HarnessRunSummary]
    comparisons: dict[str, SWEBenchRunComparison]
    score_rows: tuple[SWEBenchScoreRow, ...]
    score_text_path: Path
    score_json_path: Path
    comparison_text_paths: dict[str, Path]
    comparison_json_paths: dict[str, Path]
    report_path: Path


def run_swebench_experiment(
    *,
    dataset_name: str = DEFAULT_DATASET_NAME,
    split: str = DEFAULT_SPLIT,
    max_instances: int | None = None,
    instance_ids: list[str] | None = None,
    repos: list[str] | None = None,
    run_prefix: str,
    predictions_root: Path = DEFAULT_SWEBENCH_PREDICTIONS_ROOT,
    artifacts_root: Path = DEFAULT_SWEBENCH_EXPERIMENT_ARTIFACTS_ROOT,
    workdir: Path = DEFAULT_HARNESS_WORKDIR,
    overwrite: bool = False,
    skip_image_prep: bool = False,
    skip_index: bool = False,
    skip_wiki_preparation: bool = False,
    ingestion_url: str = DEFAULT_INGESTION_URL,
    search_service_url: str = DEFAULT_SEARCH_SERVICE_URL,
    context_source: str = "code",
    top_k: int = DEFAULT_SEARCH_TOP_K,
    github_token: str | None = None,
    stream_worker_logs: bool | None = None,
    index_poll_interval_seconds: float = DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
    index_progress_heartbeat_seconds: float = DEFAULT_PROGRESS_HEARTBEAT_SECONDS,
    index_timeout_seconds: float = DEFAULT_STATUS_TIMEOUT_SECONDS,
    wiki_poll_interval_seconds: float = DEFAULT_WIKI_POLL_INTERVAL_SECONDS,
    wiki_progress_heartbeat_seconds: float = DEFAULT_WIKI_PROGRESS_HEARTBEAT_SECONDS,
    wiki_timeout_seconds: float = DEFAULT_WIKI_TIMEOUT_SECONDS,
    model_name: str = DEFAULT_BASELINE_MODEL,
    region_name: str = DEFAULT_BASELINE_REGION,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_workers: int = 1,
    timeout_seconds: int = DEFAULT_RUN_TIMEOUT_SECONDS,
    cache_level: str = DEFAULT_CACHE_LEVEL,
    repo_registry_path: Path | None = None,
) -> SWEBenchExperimentResult:
    if not run_prefix.strip():
        raise ValueError("run_prefix must not be empty.")
    if context_source not in {"code", "wiki"}:
        raise ValueError("context_source must be 'code' or 'wiki'.")

    tasks = load_swebench_slice(
        dataset_name=dataset_name,
        split=split,
        max_instances=max_instances,
        instance_ids=instance_ids,
        repos=repos,
    )
    print(f"SWE-bench experiment: {len(tasks)} task(s) from {dataset_name} [{split}]")

    task_repo_map = {t.instance_id: t.repo for t in tasks}

    if not skip_image_prep:
        print("Preparing Docker images...")
        prepare_swebench_images(
            tasks=tasks,
            dataset_name=dataset_name,
            split=split,
            workdir=workdir,
            max_workers=max_workers,
        )

    registry_path = repo_registry_path or DEFAULT_REPO_REGISTRY_OUTPUT
    if not skip_index:
        print("Indexing repositories...")
        index_swebench_repositories(
            tasks=tasks,
            ingestion_url=ingestion_url,
            output_path=registry_path,
            github_token=github_token,
            stream_worker_logs=stream_worker_logs,
            poll_interval_seconds=index_poll_interval_seconds,
            progress_heartbeat_seconds=index_progress_heartbeat_seconds,
            timeout_seconds=index_timeout_seconds,
        )

    if not skip_wiki_preparation:
        print("Preparing wiki documentation...")
        prepare_lighthouse_wiki(
            tasks=tasks,
            ingestion_url=ingestion_url,
            repo_registry_path=registry_path,
            poll_interval_seconds=wiki_poll_interval_seconds,
            progress_heartbeat_seconds=wiki_progress_heartbeat_seconds,
            timeout_seconds=wiki_timeout_seconds,
        )

    predictions_root = predictions_root.resolve()
    predictions_root.mkdir(parents=True, exist_ok=True)
    baseline_predictions_path = predictions_root / f"{run_prefix}-baseline.jsonl"
    lighthouse_predictions_path = (
        predictions_root / f"{run_prefix}-{context_source}.jsonl"
    )
    baseline_run_id = f"{run_prefix}-baseline"
    lighthouse_run_id = f"{run_prefix}-{context_source}"

    print("Generating baseline predictions...")
    generator = BedrockPatchGenerator(
        model_name=model_name,
        region_name=region_name,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    generate_baseline_predictions(
        tasks=tasks,
        generator=generator,
        output_path=baseline_predictions_path,
        overwrite=overwrite,
    )

    print(f"Generating {context_source} Lighthouse predictions...")
    if context_source == "wiki":
        lighthouse_messages = build_wiki_lighthouse_messages(
            tasks=tasks,
            search_service_url=search_service_url,
            top_k=top_k,
            repo_registry_path=registry_path,
        )
    else:
        lighthouse_messages = build_lighthouse_messages(
            tasks=tasks,
            search_service_url=search_service_url,
            top_k=top_k,
            repo_registry_path=registry_path,
        )
    lighthouse_generator = BedrockPatchGenerator(
        model_name=model_name,
        region_name=region_name,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    generate_predictions(
        tasks=tasks,
        generator=lighthouse_generator,
        output_path=lighthouse_predictions_path,
        overwrite=overwrite,
        build_user_message=lambda task: lighthouse_messages[task.instance_id],
        progress_label=f"Generating {context_source} Lighthouse patch for",
    )

    print("Evaluating baseline predictions...")
    evaluate_swebench_predictions(
        tasks=tasks,
        dataset_name=dataset_name,
        split=split,
        predictions_path=baseline_predictions_path,
        run_id=baseline_run_id,
        workdir=workdir,
        max_workers=max_workers,
        timeout_seconds=timeout_seconds,
        cache_level=cache_level,
    )
    baseline_summary = summarize_swebench_run(
        predictions_path=baseline_predictions_path,
        run_id=baseline_run_id,
        workdir=workdir,
    )

    print(f"Evaluating {context_source} Lighthouse predictions...")
    evaluate_swebench_predictions(
        tasks=tasks,
        dataset_name=dataset_name,
        split=split,
        predictions_path=lighthouse_predictions_path,
        run_id=lighthouse_run_id,
        workdir=workdir,
        max_workers=max_workers,
        timeout_seconds=timeout_seconds,
        cache_level=cache_level,
    )
    lighthouse_summary = summarize_swebench_run(
        predictions_path=lighthouse_predictions_path,
        run_id=lighthouse_run_id,
        workdir=workdir,
    )

    print("Comparing runs...")
    comparison = compare_swebench_runs(
        baseline=baseline_summary,
        lighthouse=lighthouse_summary,
        baseline_run_id=baseline_run_id,
        lighthouse_run_id=lighthouse_run_id,
        task_repo_map=task_repo_map,
        baseline_label="baseline",
        lighthouse_label=context_source,
    )

    artifacts_root = artifacts_root.resolve()
    artifacts_root.mkdir(parents=True, exist_ok=True)
    comparison_text_path = artifacts_root / f"{run_prefix}.comparison.txt"
    comparison_json_path = artifacts_root / f"{run_prefix}.comparison.json"
    report_path = artifacts_root / f"{run_prefix}.experiment.json"

    comparison_text = render_swebench_comparison_tables(comparison)
    comparison_text_path.write_text(comparison_text + "\n", encoding="utf-8")
    comparison_json_path.write_text(
        json.dumps(_comparison_to_json(comparison), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "run_prefix": run_prefix,
                "dataset_name": dataset_name,
                "split": split,
                "task_count": len(tasks),
                "repos": sorted(set(t.repo for t in tasks)),
                "context_source": context_source,
                "top_k": top_k,
                "model_name": model_name,
                "baseline_predictions_path": str(baseline_predictions_path),
                "lighthouse_predictions_path": str(lighthouse_predictions_path),
                "baseline_run_id": baseline_run_id,
                "lighthouse_run_id": lighthouse_run_id,
                "comparison_text_path": str(comparison_text_path),
                "comparison_json_path": str(comparison_json_path),
                "comparison": _comparison_to_json(comparison),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return SWEBenchExperimentResult(
        tasks=tuple(tasks),
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


def run_swebench_experiment_suite(
    *,
    dataset_name: str = DEFAULT_DATASET_NAME,
    split: str = DEFAULT_SPLIT,
    max_instances: int | None = None,
    instance_ids: list[str] | None = None,
    repos: list[str] | None = None,
    run_prefix: str,
    predictions_root: Path = DEFAULT_SWEBENCH_PREDICTIONS_ROOT,
    artifacts_root: Path = DEFAULT_SWEBENCH_EXPERIMENT_ARTIFACTS_ROOT,
    workdir: Path = DEFAULT_HARNESS_WORKDIR,
    overwrite: bool = False,
    skip_image_prep: bool = False,
    skip_index: bool = False,
    skip_wiki_preparation: bool = False,
    ingestion_url: str = DEFAULT_INGESTION_URL,
    search_service_url: str = DEFAULT_SEARCH_SERVICE_URL,
    top_k: int = DEFAULT_SEARCH_TOP_K,
    github_token: str | None = None,
    stream_worker_logs: bool | None = None,
    index_poll_interval_seconds: float = DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
    index_progress_heartbeat_seconds: float = DEFAULT_PROGRESS_HEARTBEAT_SECONDS,
    index_timeout_seconds: float = DEFAULT_STATUS_TIMEOUT_SECONDS,
    wiki_poll_interval_seconds: float = DEFAULT_WIKI_POLL_INTERVAL_SECONDS,
    wiki_progress_heartbeat_seconds: float = DEFAULT_WIKI_PROGRESS_HEARTBEAT_SECONDS,
    wiki_timeout_seconds: float = DEFAULT_WIKI_TIMEOUT_SECONDS,
    model_name: str = DEFAULT_BASELINE_MODEL,
    region_name: str = DEFAULT_BASELINE_REGION,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_workers: int = 1,
    timeout_seconds: int = DEFAULT_RUN_TIMEOUT_SECONDS,
    cache_level: str = DEFAULT_CACHE_LEVEL,
    repo_registry_path: Path | None = None,
) -> SWEBenchExperimentSuiteResult:
    if not run_prefix.strip():
        raise ValueError("run_prefix must not be empty.")

    tasks = load_swebench_slice(
        dataset_name=dataset_name,
        split=split,
        max_instances=max_instances,
        instance_ids=instance_ids,
        repos=repos,
    )
    print(
        f"SWE-bench experiment suite: {len(tasks)} task(s) from {dataset_name} [{split}]"
    )

    task_repo_map = {t.instance_id: t.repo for t in tasks}
    registry_path = repo_registry_path or DEFAULT_REPO_REGISTRY_OUTPUT

    if not skip_image_prep:
        print("Preparing Docker images...")
        prepare_swebench_images(
            tasks=tasks,
            dataset_name=dataset_name,
            split=split,
            workdir=workdir,
            max_workers=max_workers,
        )

    if not skip_index:
        print("Indexing repositories...")
        index_swebench_repositories(
            tasks=tasks,
            ingestion_url=ingestion_url,
            output_path=registry_path,
            github_token=github_token,
            stream_worker_logs=stream_worker_logs,
            poll_interval_seconds=index_poll_interval_seconds,
            progress_heartbeat_seconds=index_progress_heartbeat_seconds,
            timeout_seconds=index_timeout_seconds,
        )

    if not skip_wiki_preparation:
        print("Preparing wiki documentation...")
        prepare_lighthouse_wiki(
            tasks=tasks,
            ingestion_url=ingestion_url,
            repo_registry_path=registry_path,
            poll_interval_seconds=wiki_poll_interval_seconds,
            progress_heartbeat_seconds=wiki_progress_heartbeat_seconds,
            timeout_seconds=wiki_timeout_seconds,
        )

    predictions_root = predictions_root.resolve()
    predictions_root.mkdir(parents=True, exist_ok=True)
    baseline_predictions_path = predictions_root / f"{run_prefix}-baseline.jsonl"
    baseline_run_id = f"{run_prefix}-baseline"

    print("Generating baseline predictions...")
    generator = BedrockPatchGenerator(
        model_name=model_name,
        region_name=region_name,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    generate_baseline_predictions(
        tasks=tasks,
        generator=generator,
        output_path=baseline_predictions_path,
        overwrite=overwrite,
    )

    print("Evaluating baseline predictions...")
    evaluate_swebench_predictions(
        tasks=tasks,
        dataset_name=dataset_name,
        split=split,
        predictions_path=baseline_predictions_path,
        run_id=baseline_run_id,
        workdir=workdir,
        max_workers=max_workers,
        timeout_seconds=timeout_seconds,
        cache_level=cache_level,
    )
    baseline_summary = summarize_swebench_run(
        predictions_path=baseline_predictions_path,
        run_id=baseline_run_id,
        workdir=workdir,
    )

    lighthouse_predictions_paths: dict[str, Path] = {}
    lighthouse_summaries: dict[str, HarnessRunSummary] = {}
    comparisons: dict[str, SWEBenchRunComparison] = {}

    for context_source in ("code", "wiki"):
        lighthouse_predictions_path = (
            predictions_root / f"{run_prefix}-{context_source}.jsonl"
        )
        lighthouse_run_id = f"{run_prefix}-{context_source}"

        print(f"Generating {context_source} Lighthouse predictions...")
        if context_source == "wiki":
            lighthouse_messages = build_wiki_lighthouse_messages(
                tasks=tasks,
                search_service_url=search_service_url,
                top_k=top_k,
                repo_registry_path=registry_path,
            )
        else:
            lighthouse_messages = build_lighthouse_messages(
                tasks=tasks,
                search_service_url=search_service_url,
                top_k=top_k,
                repo_registry_path=registry_path,
            )
        lighthouse_generator = BedrockPatchGenerator(
            model_name=model_name,
            region_name=region_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        generate_predictions(
            tasks=tasks,
            generator=lighthouse_generator,
            output_path=lighthouse_predictions_path,
            overwrite=overwrite,
            build_user_message=lambda task, msgs=lighthouse_messages: msgs[
                task.instance_id
            ],
            progress_label=f"Generating {context_source} Lighthouse patch for",
        )

        print(f"Evaluating {context_source} Lighthouse predictions...")
        evaluate_swebench_predictions(
            tasks=tasks,
            dataset_name=dataset_name,
            split=split,
            predictions_path=lighthouse_predictions_path,
            run_id=lighthouse_run_id,
            workdir=workdir,
            max_workers=max_workers,
            timeout_seconds=timeout_seconds,
            cache_level=cache_level,
        )
        lighthouse_summary = summarize_swebench_run(
            predictions_path=lighthouse_predictions_path,
            run_id=lighthouse_run_id,
            workdir=workdir,
        )

        comparison = compare_swebench_runs(
            baseline=baseline_summary,
            lighthouse=lighthouse_summary,
            baseline_run_id=baseline_run_id,
            lighthouse_run_id=lighthouse_run_id,
            task_repo_map=task_repo_map,
            baseline_label="baseline",
            lighthouse_label=context_source,
        )

        lighthouse_predictions_paths[context_source] = lighthouse_predictions_path
        lighthouse_summaries[context_source] = lighthouse_summary
        comparisons[context_source] = comparison

    score_rows = build_swebench_score_rows(
        baseline=baseline_summary,
        baseline_run_id=baseline_run_id,
        retrieval_runs={
            label: (summary, f"{run_prefix}-{label}")
            for label, summary in lighthouse_summaries.items()
        },
    )

    artifacts_root = artifacts_root.resolve()
    artifacts_root.mkdir(parents=True, exist_ok=True)
    score_text_path = artifacts_root / f"{run_prefix}.score.txt"
    score_json_path = artifacts_root / f"{run_prefix}.score.json"
    comparison_text_paths: dict[str, Path] = {}
    comparison_json_paths: dict[str, Path] = {}

    score_text = render_swebench_score_table(score_rows)
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

    for ctx_source, comparison in comparisons.items():
        comparison_text_path = (
            artifacts_root / f"{run_prefix}.{ctx_source}.comparison.txt"
        )
        comparison_json_path = (
            artifacts_root / f"{run_prefix}.{ctx_source}.comparison.json"
        )
        comparison_text_paths[ctx_source] = comparison_text_path
        comparison_json_paths[ctx_source] = comparison_json_path
        comparison_text_path.write_text(
            render_swebench_comparison_tables(comparison) + "\n",
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
                "dataset_name": dataset_name,
                "split": split,
                "task_count": len(tasks),
                "repos": sorted(set(t.repo for t in tasks)),
                "model_name": model_name,
                "top_k": top_k,
                "baseline_predictions_path": str(baseline_predictions_path),
                "baseline_run_id": baseline_run_id,
                "lighthouse_predictions_paths": {
                    label: str(path) for label, path in lighthouse_predictions_paths.items()
                },
                "lighthouse_run_ids": {
                    label: f"{run_prefix}-{label}" for label in lighthouse_summaries
                },
                "score_text_path": str(score_text_path),
                "score_json_path": str(score_json_path),
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
                    label: _comparison_to_json(comp)
                    for label, comp in comparisons.items()
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return SWEBenchExperimentSuiteResult(
        tasks=tuple(tasks),
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


def _comparison_to_json(comparison: SWEBenchRunComparison) -> dict[str, object]:
    return {
        "baseline_label": comparison.baseline_label,
        "lighthouse_label": comparison.lighthouse_label,
        "improved_instances": comparison.improved_instances,
        "regressed_instances": comparison.regressed_instances,
        "unchanged_instances": comparison.unchanged_instances,
        "baseline": _summary_to_json(comparison.baseline),
        "lighthouse": _summary_to_json(comparison.lighthouse),
        "instance_comparisons": [
            {
                "instance_id": inst.instance_id,
                "repo": inst.repo,
                "baseline_status": inst.baseline_status,
                "lighthouse_status": inst.lighthouse_status,
                "baseline_fail_to_pass_failures": inst.baseline_fail_to_pass_failures,
                "lighthouse_fail_to_pass_failures": inst.lighthouse_fail_to_pass_failures,
                "delta": inst.delta,
            }
            for inst in comparison.instance_comparisons
        ],
    }


def _summary_to_json(summary: HarnessRunSummary) -> dict[str, object]:
    return {
        "total_instances": summary.total_instances,
        "submitted_instances": summary.submitted_instances,
        "completed_instances": summary.completed_instances,
        "resolved_instances": summary.resolved_instances,
        "unresolved_instances": summary.unresolved_instances,
        "empty_patch_instances": summary.empty_patch_instances,
        "error_instances": summary.error_instances,
    }
