from __future__ import annotations

import argparse
from pathlib import Path

from eval.bedrock import (
    DEFAULT_BASELINE_MODEL,
    DEFAULT_BASELINE_REGION,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    BedrockPatchGenerator,
)
from eval.slice import (
    DEFAULT_DATASET_NAME,
    DEFAULT_SPLIT,
    SWEBenchTask,
    load_swebench_slice,
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
from eval.summary import HarnessRunSummary, summarize_swebench_run
from eval.synthetic import (
    DEFAULT_SYNTHETIC_FAMILY,
    DEFAULT_SYNTHETIC_RUNS_ROOT,
    DEFAULT_SYNTHETIC_TASK_TYPE,
    DEFAULT_SYNTHETIC_WORKSPACE_ROOT,
    PreparedSyntheticWorkspace,
    prepare_synthetic_workspace,
    select_synthetic_tasks,
    shared_resolved_repository,
)
from eval.synthetic.compare import (
    SyntheticRunComparison,
    render_synthetic_score_table,
    compare_synthetic_runs,
    render_synthetic_comparison_tables,
)
from eval.synthetic.eval import (
    SyntheticRunSummary,
    evaluate_synthetic_predictions,
    list_synthetic_run_ids,
    summarize_synthetic_run,
    validate_prepared_synthetic_workspace,
)
from eval.synthetic.experiment import (
    DEFAULT_SYNTHETIC_EXPERIMENT_ARTIFACTS_ROOT,
    DEFAULT_SYNTHETIC_PREDICTIONS_ROOT,
    SyntheticExperimentResult,
    SyntheticExperimentSuiteResult,
    run_synthetic_experiment,
    run_synthetic_experiment_suite,
)
from eval.synthetic.lighthouse import (
    build_synthetic_lighthouse_messages,
    index_synthetic_repository,
    prepare_synthetic_wiki,
)
from eval.synthetic.metadata import resolve_synthetic_experiment_metadata
from eval.synthetic.predictions import (
    generate_synthetic_baseline_predictions,
    generate_synthetic_predictions as generate_synthetic_predictions_jsonl,
)
from eval.wiki import (
    DEFAULT_WIKI_INGESTION_URL,
    DEFAULT_WIKI_POLL_INTERVAL_SECONDS,
    DEFAULT_WIKI_PROGRESS_HEARTBEAT_SECONDS,
    DEFAULT_WIKI_TIMEOUT_SECONDS,
    build_wiki_lighthouse_messages,
    prepare_lighthouse_wiki,
)


def _add_synthetic_selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--family",
        default=DEFAULT_SYNTHETIC_FAMILY,
        help="Synthetic family name to load",
    )
    parser.add_argument(
        "--task-count",
        type=int,
        default=None,
        help="Select N synthetic tasks deterministically from the family",
    )
    parser.add_argument(
        "--task-type",
        choices=[DEFAULT_SYNTHETIC_TASK_TYPE],
        default=None,
        help="Synthetic task type to select",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Selection seed for synthetic task subsets",
    )
    parser.add_argument(
        "--shared-library-repo-count",
        type=int,
        default=None,
        help="Override the requested shared library repo count",
    )


def _add_synthetic_workspace_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace-root",
        default=str(DEFAULT_SYNTHETIC_WORKSPACE_ROOT),
        help="Root directory for materialized synthetic benchmark repos",
    )
    parser.add_argument(
        "--force-workspace",
        action="store_true",
        help="Rebuild the selected synthetic workspace from scratch",
    )


def _add_synthetic_metadata_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_generation_region: bool = False,
    include_search_top_k: bool = False,
) -> None:
    if include_generation_region:
        parser.add_argument(
            "--generation-region-name",
            default="",
            help="Optional generation region to stamp into synthetic run metadata",
        )
    if include_search_top_k:
        parser.add_argument(
            "--search-top-k",
            type=int,
            default=None,
            help="Optional retrieval top-k to stamp into synthetic run metadata",
        )
    parser.add_argument(
        "--indexing-embedding-strategy",
        default=None,
        help="Override the indexing embedding strategy recorded in experiment metadata",
    )
    parser.add_argument(
        "--indexing-embedding-model",
        default=None,
        help="Override the indexing embedding model recorded in experiment metadata",
    )
    parser.add_argument(
        "--query-embedding-strategy",
        default=None,
        help="Override the query embedding strategy recorded in experiment metadata",
    )
    parser.add_argument(
        "--query-embedding-model",
        default=None,
        help="Override the query embedding model recorded in experiment metadata",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal eval package CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_slice = subparsers.add_parser(
        "show-slice",
        help="Load and print a SWE-bench slice",
    )
    show_slice.add_argument(
        "--dataset-name",
        default=DEFAULT_DATASET_NAME,
        help="Hugging Face dataset name to load",
    )
    show_slice.add_argument(
        "--split",
        default=DEFAULT_SPLIT,
        help="Dataset split to load",
    )
    show_slice.add_argument(
        "--max-instances",
        type=int,
        default=None,
        help="Load the first N instances in dataset order",
    )
    show_slice.add_argument(
        "--instance-id",
        action="append",
        default=[],
        help="Explicit SWE-bench instance id to include; may be repeated",
    )

    prepare_images = subparsers.add_parser(
        "prepare-images",
        help="Prepare SWE-bench Docker images for a selected slice",
    )
    prepare_images.add_argument(
        "--dataset-name",
        default=DEFAULT_DATASET_NAME,
        help="Hugging Face dataset name to load",
    )
    prepare_images.add_argument(
        "--split",
        default=DEFAULT_SPLIT,
        help="Dataset split to load",
    )
    prepare_images.add_argument(
        "--max-instances",
        type=int,
        default=None,
        help="Prepare images for the first N instances in dataset order",
    )
    prepare_images.add_argument(
        "--instance-id",
        action="append",
        default=[],
        help="Explicit SWE-bench instance id to include; may be repeated",
    )
    prepare_images.add_argument(
        "--workdir",
        default=str(DEFAULT_HARNESS_WORKDIR),
        help="Working directory for SWE-bench harness artifacts and logs",
    )
    prepare_images.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Maximum parallel harness workers",
    )

    index_repos = subparsers.add_parser(
        "index-repos",
        help="Index the repositories referenced by a selected SWE-bench slice",
    )
    index_repos.add_argument(
        "--dataset-name",
        default=DEFAULT_DATASET_NAME,
        help="Hugging Face dataset name to load",
    )
    index_repos.add_argument(
        "--split",
        default=DEFAULT_SPLIT,
        help="Dataset split to load",
    )
    index_repos.add_argument(
        "--max-instances",
        type=int,
        default=None,
        help="Index repositories for the first N instances in dataset order",
    )
    index_repos.add_argument(
        "--instance-id",
        action="append",
        default=[],
        help="Explicit SWE-bench instance id to include; may be repeated",
    )
    index_repos.add_argument(
        "--ingestion-url",
        default=DEFAULT_INGESTION_URL,
        help="Base URL for the Lighthouse ingestion service",
    )
    index_repos.add_argument(
        "--github-token",
        default=None,
        help="Optional GitHub token for metadata lookup and ingestion",
    )
    index_repos.add_argument(
        "--output",
        default=str(DEFAULT_REPO_REGISTRY_OUTPUT),
        help="Path to the repo registry JSON file to write",
    )
    index_repos.add_argument(
        "--status-poll-interval",
        type=float,
        default=DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
        help="Seconds between ingestion status polls",
    )
    index_repos.add_argument(
        "--progress-heartbeat-seconds",
        type=float,
        default=DEFAULT_PROGRESS_HEARTBEAT_SECONDS,
        help="Seconds between 'still waiting' progress heartbeat lines",
    )
    index_repos.add_argument(
        "--status-timeout-seconds",
        type=float,
        default=DEFAULT_STATUS_TIMEOUT_SECONDS,
        help="Maximum total wait time for indexing completion",
    )
    index_repos.add_argument(
        "--stream-worker-logs",
        dest="stream_worker_logs",
        action="store_true",
        help="Stream local ingestion-worker Docker logs while waiting for indexing",
    )
    index_repos.add_argument(
        "--no-stream-worker-logs",
        dest="stream_worker_logs",
        action="store_false",
        help="Disable local ingestion-worker Docker log streaming",
    )
    index_repos.set_defaults(stream_worker_logs=None)
    index_repos.add_argument(
        "--skip-wiki-preparation",
        action="store_true",
        help="Skip bundled wiki generation after repository indexing completes",
    )
    index_repos.add_argument(
        "--wiki-poll-interval",
        type=float,
        default=DEFAULT_WIKI_POLL_INTERVAL_SECONDS,
        help="Seconds between wiki status polls during bundled preprocessing",
    )
    index_repos.add_argument(
        "--wiki-progress-heartbeat-seconds",
        type=float,
        default=DEFAULT_WIKI_PROGRESS_HEARTBEAT_SECONDS,
        help="Seconds between bundled wiki preparation heartbeat lines",
    )
    index_repos.add_argument(
        "--wiki-timeout-seconds",
        type=float,
        default=DEFAULT_WIKI_TIMEOUT_SECONDS,
        help="Maximum total wait time for bundled wiki generation",
    )

    prepare_wiki = subparsers.add_parser(
        "prepare-wiki",
        help="Generate Lighthouse wiki documentation for the repositories in a selected SWE-bench slice",
    )
    prepare_wiki.add_argument(
        "--dataset-name",
        default=DEFAULT_DATASET_NAME,
        help="Hugging Face dataset name to load",
    )
    prepare_wiki.add_argument(
        "--split",
        default=DEFAULT_SPLIT,
        help="Dataset split to load",
    )
    prepare_wiki.add_argument(
        "--max-instances",
        type=int,
        default=None,
        help="Prepare wiki docs for the first N instances in dataset order",
    )
    prepare_wiki.add_argument(
        "--instance-id",
        action="append",
        default=[],
        help="Explicit SWE-bench instance id to include; may be repeated",
    )
    prepare_wiki.add_argument(
        "--ingestion-url",
        default=DEFAULT_WIKI_INGESTION_URL,
        help="Base URL for the Lighthouse ingestion service",
    )
    prepare_wiki.add_argument(
        "--repo-registry",
        default=None,
        help="Path to a JSON file mapping owner/repo to github_repo_id and branch",
    )
    prepare_wiki.add_argument(
        "--github-repo-id",
        type=int,
        default=None,
        help="GitHub repo id override when all selected tasks are from one repository",
    )
    prepare_wiki.add_argument(
        "--branch",
        default=DEFAULT_LIGHTHOUSE_BRANCH,
        help="Branch override when using --github-repo-id",
    )
    prepare_wiki.add_argument(
        "--status-poll-interval",
        type=float,
        default=DEFAULT_WIKI_POLL_INTERVAL_SECONDS,
        help="Seconds between wiki status polls",
    )
    prepare_wiki.add_argument(
        "--progress-heartbeat-seconds",
        type=float,
        default=DEFAULT_WIKI_PROGRESS_HEARTBEAT_SECONDS,
        help="Seconds between 'still waiting' progress heartbeat lines",
    )
    prepare_wiki.add_argument(
        "--status-timeout-seconds",
        type=float,
        default=DEFAULT_WIKI_TIMEOUT_SECONDS,
        help="Maximum total wait time for wiki generation completion",
    )

    generate_baseline = subparsers.add_parser(
        "generate-baseline",
        help="Generate baseline SWE-bench prediction JSONL with Bedrock",
    )
    generate_baseline.add_argument(
        "--dataset-name",
        default=DEFAULT_DATASET_NAME,
        help="Hugging Face dataset name to load",
    )
    generate_baseline.add_argument(
        "--split",
        default=DEFAULT_SPLIT,
        help="Dataset split to load",
    )
    generate_baseline.add_argument(
        "--max-instances",
        type=int,
        default=None,
        help="Generate predictions for the first N instances in dataset order",
    )
    generate_baseline.add_argument(
        "--instance-id",
        action="append",
        default=[],
        help="Explicit SWE-bench instance id to include; may be repeated",
    )
    generate_baseline.add_argument(
        "--model",
        default=DEFAULT_BASELINE_MODEL,
        help="Bedrock model in the form bedrock/<model-id>",
    )
    generate_baseline.add_argument(
        "--output",
        required=True,
        help="Path to the predictions .jsonl file to write",
    )
    generate_baseline.add_argument(
        "--region-name",
        default=DEFAULT_BASELINE_REGION,
        help="AWS region for Bedrock generation",
    )
    generate_baseline.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help="Sampling temperature for Bedrock generation",
    )
    generate_baseline.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="Maximum response tokens for Bedrock generation",
    )
    generate_baseline.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing predictions file",
    )

    generate_lighthouse = subparsers.add_parser(
        "generate-lighthouse",
        help="Generate SWE-bench prediction JSONL with Lighthouse retrieval context",
    )
    generate_lighthouse.add_argument(
        "--dataset-name",
        default=DEFAULT_DATASET_NAME,
        help="Hugging Face dataset name to load",
    )
    generate_lighthouse.add_argument(
        "--split",
        default=DEFAULT_SPLIT,
        help="Dataset split to load",
    )
    generate_lighthouse.add_argument(
        "--max-instances",
        type=int,
        default=None,
        help="Generate predictions for the first N instances in dataset order",
    )
    generate_lighthouse.add_argument(
        "--instance-id",
        action="append",
        default=[],
        help="Explicit SWE-bench instance id to include; may be repeated",
    )
    generate_lighthouse.add_argument(
        "--model",
        default=DEFAULT_BASELINE_MODEL,
        help="Bedrock model in the form bedrock/<model-id>",
    )
    generate_lighthouse.add_argument(
        "--output",
        required=True,
        help="Path to the predictions .jsonl file to write",
    )
    generate_lighthouse.add_argument(
        "--region-name",
        default=DEFAULT_BASELINE_REGION,
        help="AWS region for Bedrock generation",
    )
    generate_lighthouse.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help="Sampling temperature for Bedrock generation",
    )
    generate_lighthouse.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="Maximum response tokens for Bedrock generation",
    )
    generate_lighthouse.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing predictions file",
    )
    generate_lighthouse.add_argument(
        "--search-url",
        default=DEFAULT_SEARCH_SERVICE_URL,
        help="Base URL for the Lighthouse search service",
    )
    generate_lighthouse.add_argument(
        "--repo-registry",
        default=None,
        help="Path to a JSON file mapping owner/repo to github_repo_id and branch",
    )
    generate_lighthouse.add_argument(
        "--github-repo-id",
        type=int,
        default=None,
        help="GitHub repo id override when all selected tasks are from one repository",
    )
    generate_lighthouse.add_argument(
        "--branch",
        default=DEFAULT_LIGHTHOUSE_BRANCH,
        help="Branch override when using --github-repo-id",
    )
    generate_lighthouse.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_SEARCH_TOP_K,
        help="Number of Lighthouse snippets to request per task",
    )
    generate_lighthouse.add_argument(
        "--context-source",
        choices=["code", "wiki"],
        default="code",
        help="Which Lighthouse retrieval source to use for prompt context",
    )

    evaluate = subparsers.add_parser(
        "evaluate",
        help="Evaluate SWE-bench predictions with the official harness",
    )
    evaluate.add_argument(
        "--dataset-name",
        default=DEFAULT_DATASET_NAME,
        help="Hugging Face dataset name to load",
    )
    evaluate.add_argument(
        "--split",
        default=DEFAULT_SPLIT,
        help="Dataset split to load",
    )
    evaluate.add_argument(
        "--max-instances",
        type=int,
        default=None,
        help="Evaluate the first N instances in dataset order",
    )
    evaluate.add_argument(
        "--instance-id",
        action="append",
        default=[],
        help="Explicit SWE-bench instance id to include; may be repeated",
    )
    evaluate.add_argument(
        "--predictions",
        required=True,
        help="Path to the predictions .jsonl or .json file",
    )
    evaluate.add_argument(
        "--run-id",
        required=True,
        help="Harness run identifier",
    )
    evaluate.add_argument(
        "--workdir",
        default=str(DEFAULT_HARNESS_WORKDIR),
        help="Working directory for SWE-bench harness artifacts and logs",
    )
    evaluate.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Maximum parallel harness workers",
    )
    evaluate.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_RUN_TIMEOUT_SECONDS,
        help="Per-instance test timeout in seconds",
    )
    evaluate.add_argument(
        "--cache-level",
        default=DEFAULT_CACHE_LEVEL,
        choices=["none", "base", "env", "instance"],
        help="Harness image cache level",
    )

    summarize = subparsers.add_parser(
        "summarize",
        help="Print a human-readable summary for a SWE-bench harness run",
    )
    summarize.add_argument(
        "--predictions",
        required=True,
        help="Path to the predictions .jsonl or .json file used for the run",
    )
    summarize.add_argument(
        "--run-id",
        required=True,
        help="Harness run identifier",
    )
    summarize.add_argument(
        "--workdir",
        default=str(DEFAULT_HARNESS_WORKDIR),
        help="Working directory for SWE-bench harness artifacts and logs",
    )

    show_synthetic = subparsers.add_parser(
        "show-synthetic",
        help="Load and print a synthetic benchmark selection",
    )
    _add_synthetic_selection_arguments(show_synthetic)

    prepare_synthetic = subparsers.add_parser(
        "prepare-synthetic",
        help="Materialize and validate a synthetic benchmark selection",
    )
    _add_synthetic_selection_arguments(prepare_synthetic)
    _add_synthetic_workspace_arguments(prepare_synthetic)

    index_synthetic = subparsers.add_parser(
        "index-synthetic",
        help="Index the shared synthetic library repository in Lighthouse",
    )
    _add_synthetic_selection_arguments(index_synthetic)
    _add_synthetic_workspace_arguments(index_synthetic)
    index_synthetic.add_argument(
        "--ingestion-url",
        default=DEFAULT_INGESTION_URL,
        help="Base URL for the Lighthouse ingestion service",
    )
    index_synthetic.add_argument(
        "--github-token",
        default=None,
        help="Optional GitHub token to forward to the ingestion service",
    )
    index_synthetic.add_argument(
        "--status-poll-interval",
        type=float,
        default=DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
        help="Seconds between ingestion status polls",
    )
    index_synthetic.add_argument(
        "--progress-heartbeat-seconds",
        type=float,
        default=DEFAULT_PROGRESS_HEARTBEAT_SECONDS,
        help="Seconds between 'still waiting' progress heartbeat lines",
    )
    index_synthetic.add_argument(
        "--status-timeout-seconds",
        type=float,
        default=DEFAULT_STATUS_TIMEOUT_SECONDS,
        help="Maximum total wait time for indexing completion",
    )
    index_synthetic.add_argument(
        "--stream-worker-logs",
        dest="stream_worker_logs",
        action="store_true",
        help="Stream local ingestion-worker Docker logs while waiting for indexing",
    )
    index_synthetic.add_argument(
        "--no-stream-worker-logs",
        dest="stream_worker_logs",
        action="store_false",
        help="Disable local ingestion-worker Docker log streaming",
    )
    index_synthetic.set_defaults(stream_worker_logs=None)
    index_synthetic.add_argument(
        "--skip-wiki-preparation",
        action="store_true",
        help="Skip bundled wiki generation after synthetic indexing completes",
    )
    index_synthetic.add_argument(
        "--wiki-poll-interval",
        type=float,
        default=DEFAULT_WIKI_POLL_INTERVAL_SECONDS,
        help="Seconds between wiki status polls during bundled preprocessing",
    )
    index_synthetic.add_argument(
        "--wiki-progress-heartbeat-seconds",
        type=float,
        default=DEFAULT_WIKI_PROGRESS_HEARTBEAT_SECONDS,
        help="Seconds between bundled wiki preparation heartbeat lines",
    )
    index_synthetic.add_argument(
        "--wiki-timeout-seconds",
        type=float,
        default=DEFAULT_WIKI_TIMEOUT_SECONDS,
        help="Maximum total wait time for bundled wiki generation",
    )

    prepare_synthetic_wiki = subparsers.add_parser(
        "prepare-synthetic-wiki",
        help="Generate Lighthouse wiki documentation for the shared synthetic library",
    )
    _add_synthetic_selection_arguments(prepare_synthetic_wiki)
    _add_synthetic_workspace_arguments(prepare_synthetic_wiki)
    prepare_synthetic_wiki.add_argument(
        "--ingestion-url",
        default=DEFAULT_WIKI_INGESTION_URL,
        help="Base URL for the Lighthouse ingestion service",
    )
    prepare_synthetic_wiki.add_argument(
        "--status-poll-interval",
        type=float,
        default=DEFAULT_WIKI_POLL_INTERVAL_SECONDS,
        help="Seconds between wiki status polls",
    )
    prepare_synthetic_wiki.add_argument(
        "--progress-heartbeat-seconds",
        type=float,
        default=DEFAULT_WIKI_PROGRESS_HEARTBEAT_SECONDS,
        help="Seconds between 'still waiting' progress heartbeat lines",
    )
    prepare_synthetic_wiki.add_argument(
        "--status-timeout-seconds",
        type=float,
        default=DEFAULT_WIKI_TIMEOUT_SECONDS,
        help="Maximum total wait time for wiki generation completion",
    )

    generate_synthetic_baseline = subparsers.add_parser(
        "generate-synthetic-baseline",
        help="Generate synthetic baseline prediction JSONL with Bedrock",
    )
    _add_synthetic_selection_arguments(generate_synthetic_baseline)
    _add_synthetic_workspace_arguments(generate_synthetic_baseline)
    generate_synthetic_baseline.add_argument(
        "--model",
        default=DEFAULT_BASELINE_MODEL,
        help="Bedrock model in the form bedrock/<model-id>",
    )
    generate_synthetic_baseline.add_argument(
        "--output",
        required=True,
        help="Path to the predictions .jsonl file to write",
    )
    generate_synthetic_baseline.add_argument(
        "--region-name",
        default=DEFAULT_BASELINE_REGION,
        help="AWS region for Bedrock generation",
    )
    generate_synthetic_baseline.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help="Sampling temperature for Bedrock generation",
    )
    generate_synthetic_baseline.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="Maximum response tokens for Bedrock generation",
    )
    generate_synthetic_baseline.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing predictions file",
    )

    generate_synthetic_lighthouse = subparsers.add_parser(
        "generate-synthetic-lighthouse",
        help="Generate synthetic prediction JSONL with Lighthouse retrieval context",
    )
    _add_synthetic_selection_arguments(generate_synthetic_lighthouse)
    _add_synthetic_workspace_arguments(generate_synthetic_lighthouse)
    generate_synthetic_lighthouse.add_argument(
        "--model",
        default=DEFAULT_BASELINE_MODEL,
        help="Bedrock model in the form bedrock/<model-id>",
    )
    generate_synthetic_lighthouse.add_argument(
        "--output",
        required=True,
        help="Path to the predictions .jsonl file to write",
    )
    generate_synthetic_lighthouse.add_argument(
        "--region-name",
        default=DEFAULT_BASELINE_REGION,
        help="AWS region for Bedrock generation",
    )
    generate_synthetic_lighthouse.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help="Sampling temperature for Bedrock generation",
    )
    generate_synthetic_lighthouse.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="Maximum response tokens for Bedrock generation",
    )
    generate_synthetic_lighthouse.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing predictions file",
    )
    generate_synthetic_lighthouse.add_argument(
        "--search-url",
        default=DEFAULT_SEARCH_SERVICE_URL,
        help="Base URL for the Lighthouse search service",
    )
    generate_synthetic_lighthouse.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_SEARCH_TOP_K,
        help="Number of Lighthouse snippets to request per task",
    )
    generate_synthetic_lighthouse.add_argument(
        "--context-source",
        choices=["code", "wiki", "code+wiki"],
        default="code",
        help="Which Lighthouse retrieval source to use for prompt context",
    )

    evaluate_synthetic = subparsers.add_parser(
        "evaluate-synthetic",
        help="Evaluate synthetic predictions with the local synthetic evaluator",
    )
    _add_synthetic_selection_arguments(evaluate_synthetic)
    _add_synthetic_workspace_arguments(evaluate_synthetic)
    evaluate_synthetic.add_argument(
        "--predictions",
        required=True,
        help="Path to the synthetic predictions .jsonl file",
    )
    evaluate_synthetic.add_argument(
        "--run-id",
        required=True,
        help="Synthetic run identifier",
    )
    evaluate_synthetic.add_argument(
        "--runs-root",
        default=str(DEFAULT_SYNTHETIC_RUNS_ROOT),
        help="Directory where synthetic evaluation runs are stored",
    )
    evaluate_synthetic.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing synthetic run directory",
    )
    _add_synthetic_metadata_arguments(
        evaluate_synthetic,
        include_generation_region=True,
        include_search_top_k=True,
    )

    summarize_synthetic = subparsers.add_parser(
        "summarize-synthetic",
        help="Print a human-readable summary for a synthetic evaluation run",
    )
    summarize_synthetic.add_argument(
        "--run-id",
        required=True,
        help="Synthetic run identifier",
    )
    summarize_synthetic.add_argument(
        "--runs-root",
        default=str(DEFAULT_SYNTHETIC_RUNS_ROOT),
        help="Directory where synthetic evaluation runs are stored",
    )

    compare_synthetic = subparsers.add_parser(
        "compare-synthetic",
        help="Compare a Lighthouse synthetic run against a baseline run and print tables",
    )
    compare_synthetic.add_argument(
        "--baseline-run-id",
        required=True,
        help="Synthetic baseline run identifier",
    )
    compare_synthetic.add_argument(
        "--lighthouse-run-id",
        required=True,
        help="Synthetic Lighthouse run identifier",
    )
    compare_synthetic.add_argument(
        "--runs-root",
        default=str(DEFAULT_SYNTHETIC_RUNS_ROOT),
        help="Directory where synthetic evaluation runs are stored",
    )
    compare_synthetic.add_argument(
        "--baseline-label",
        default="baseline",
        help="Display label for the baseline run",
    )
    compare_synthetic.add_argument(
        "--lighthouse-label",
        default="lighthouse",
        help="Display label for the Lighthouse run",
    )

    run_synthetic_experiment = subparsers.add_parser(
        "run-synthetic-experiment",
        help="Prepare, index, generate, evaluate, and compare a synthetic experiment in one command",
    )
    _add_synthetic_selection_arguments(run_synthetic_experiment)
    _add_synthetic_workspace_arguments(run_synthetic_experiment)
    run_synthetic_experiment.add_argument(
        "--run-prefix",
        required=True,
        help="Shared prefix used for baseline/lighthouse run ids and prediction files",
    )
    run_synthetic_experiment.add_argument(
        "--predictions-root",
        default=str(DEFAULT_SYNTHETIC_PREDICTIONS_ROOT),
        help="Directory where generated synthetic prediction JSONL files are stored",
    )
    run_synthetic_experiment.add_argument(
        "--runs-root",
        default=str(DEFAULT_SYNTHETIC_RUNS_ROOT),
        help="Directory where synthetic evaluation runs are stored",
    )
    run_synthetic_experiment.add_argument(
        "--artifacts-root",
        default=str(DEFAULT_SYNTHETIC_EXPERIMENT_ARTIFACTS_ROOT),
        help="Directory where experiment comparison/report artifacts are written",
    )
    run_synthetic_experiment.add_argument(
        "--ingestion-url",
        default=DEFAULT_INGESTION_URL,
        help="Base URL for the Lighthouse ingestion service",
    )
    run_synthetic_experiment.add_argument(
        "--search-url",
        default=DEFAULT_SEARCH_SERVICE_URL,
        help="Base URL for the Lighthouse search service",
    )
    run_synthetic_experiment.add_argument(
        "--github-token",
        default=None,
        help="Optional GitHub token to forward to the ingestion service",
    )
    run_synthetic_experiment.add_argument(
        "--model",
        default=DEFAULT_BASELINE_MODEL,
        help="Generation model used for both synthetic baseline and Lighthouse paths",
    )
    run_synthetic_experiment.add_argument(
        "--region-name",
        default=DEFAULT_BASELINE_REGION,
        help="AWS region used for both synthetic baseline and Lighthouse generation",
    )
    run_synthetic_experiment.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help="Sampling temperature for both synthetic generation paths",
    )
    run_synthetic_experiment.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="Maximum response tokens for both synthetic generation paths",
    )
    run_synthetic_experiment.add_argument(
        "--context-source",
        choices=["code", "wiki", "code+wiki", "all"],
        default="code",
        help=(
            "Which Lighthouse retrieval source to use: code, wiki, code+wiki, "
            "or all (baseline + code + wiki + code+wiki)"
        ),
    )
    run_synthetic_experiment.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_SEARCH_TOP_K,
        help="Number of Lighthouse snippets to request per task",
    )
    run_synthetic_experiment.add_argument(
        "--skip-index",
        action="store_true",
        help="Reuse the existing synthetic provider index instead of re-indexing it",
    )
    run_synthetic_experiment.add_argument(
        "--skip-wiki-preparation",
        action="store_true",
        help="Reuse the existing synthetic provider wiki instead of regenerating it",
    )
    run_synthetic_experiment.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip synthetic task validity checks before running the experiment",
    )
    run_synthetic_experiment.add_argument(
        "--status-poll-interval",
        type=float,
        default=DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
        help="Seconds between indexing status polls",
    )
    run_synthetic_experiment.add_argument(
        "--progress-heartbeat-seconds",
        type=float,
        default=DEFAULT_PROGRESS_HEARTBEAT_SECONDS,
        help="Seconds between indexing progress heartbeat lines",
    )
    run_synthetic_experiment.add_argument(
        "--status-timeout-seconds",
        type=float,
        default=DEFAULT_STATUS_TIMEOUT_SECONDS,
        help="Maximum total wait time for indexing completion",
    )
    run_synthetic_experiment.add_argument(
        "--wiki-poll-interval",
        type=float,
        default=DEFAULT_WIKI_POLL_INTERVAL_SECONDS,
        help="Seconds between synthetic wiki status polls",
    )
    run_synthetic_experiment.add_argument(
        "--wiki-progress-heartbeat-seconds",
        type=float,
        default=DEFAULT_WIKI_PROGRESS_HEARTBEAT_SECONDS,
        help="Seconds between synthetic wiki progress heartbeat lines",
    )
    run_synthetic_experiment.add_argument(
        "--wiki-timeout-seconds",
        type=float,
        default=DEFAULT_WIKI_TIMEOUT_SECONDS,
        help="Maximum total wait time for synthetic wiki generation",
    )
    run_synthetic_experiment.add_argument(
        "--stream-worker-logs",
        dest="stream_worker_logs",
        action="store_true",
        help="Stream local ingestion-worker Docker logs while indexing",
    )
    run_synthetic_experiment.add_argument(
        "--no-stream-worker-logs",
        dest="stream_worker_logs",
        action="store_false",
        help="Disable local ingestion-worker Docker log streaming",
    )
    run_synthetic_experiment.set_defaults(stream_worker_logs=None)
    run_synthetic_experiment.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing prediction, run, and artifact outputs for this prefix",
    )
    _add_synthetic_metadata_arguments(run_synthetic_experiment)

    return parser


def _cmd_show_slice(args: argparse.Namespace) -> int:
    _validate_slice_selection(args)

    tasks = load_swebench_slice(
        dataset_name=args.dataset_name,
        split=args.split,
        max_instances=args.max_instances,
        instance_ids=args.instance_id,
    )

    _print_slice(tasks, args.dataset_name, args.split)
    return 0


def _cmd_prepare_images(args: argparse.Namespace) -> int:
    _validate_slice_selection(args)
    if args.max_workers < 1:
        raise ValueError("--max-workers must be at least 1")

    tasks = load_swebench_slice(
        dataset_name=args.dataset_name,
        split=args.split,
        max_instances=args.max_instances,
        instance_ids=args.instance_id,
    )

    _print_slice(tasks, args.dataset_name, args.split)
    image_names = prepare_swebench_images(
        tasks=tasks,
        dataset_name=args.dataset_name,
        split=args.split,
        workdir=Path(args.workdir),
        max_workers=args.max_workers,
    )
    print("Prepared images:")
    for image_name in image_names:
        print(f"  - {image_name}")
    return 0


def _cmd_index_repos(args: argparse.Namespace) -> int:
    _validate_slice_selection(args)
    if args.progress_heartbeat_seconds < 1:
        raise ValueError("--progress-heartbeat-seconds must be at least 1")
    if args.wiki_progress_heartbeat_seconds < 1:
        raise ValueError("--wiki-progress-heartbeat-seconds must be at least 1")

    tasks = load_swebench_slice(
        dataset_name=args.dataset_name,
        split=args.split,
        max_instances=args.max_instances,
        instance_ids=args.instance_id,
    )

    _print_slice(tasks, args.dataset_name, args.split)
    output_path = index_swebench_repositories(
        tasks=tasks,
        ingestion_url=args.ingestion_url,
        output_path=Path(args.output),
        github_token=args.github_token,
        stream_worker_logs=args.stream_worker_logs,
        poll_interval_seconds=args.status_poll_interval,
        progress_heartbeat_seconds=args.progress_heartbeat_seconds,
        timeout_seconds=args.status_timeout_seconds,
    )
    print(f"Repository registry: {output_path}")
    if args.skip_wiki_preparation:
        print("Skipping bundled wiki preparation.")
        return 0

    prepare_lighthouse_wiki(
        tasks=tasks,
        ingestion_url=args.ingestion_url,
        repo_registry_path=Path(output_path),
        poll_interval_seconds=args.wiki_poll_interval,
        progress_heartbeat_seconds=args.wiki_progress_heartbeat_seconds,
        timeout_seconds=args.wiki_timeout_seconds,
    )
    print("Wiki preparation completed.")
    return 0


def _cmd_prepare_wiki(args: argparse.Namespace) -> int:
    _validate_slice_selection(args)
    if args.progress_heartbeat_seconds < 1:
        raise ValueError("--progress-heartbeat-seconds must be at least 1")
    if args.github_repo_id is None and not args.repo_registry:
        raise ValueError(
            "Provide either --repo-registry or --github-repo-id for wiki preparation."
        )

    tasks = load_swebench_slice(
        dataset_name=args.dataset_name,
        split=args.split,
        max_instances=args.max_instances,
        instance_ids=args.instance_id,
    )

    _print_slice(tasks, args.dataset_name, args.split)
    print(f"Ingestion service URL: {args.ingestion_url}")
    if args.repo_registry:
        print(f"Repository registry: {Path(args.repo_registry).resolve()}")
    elif args.github_repo_id is not None:
        print(f"GitHub repo id override: {args.github_repo_id}")
        print(f"Branch override: {args.branch}")

    prepare_lighthouse_wiki(
        tasks=tasks,
        ingestion_url=args.ingestion_url,
        repo_registry_path=Path(args.repo_registry) if args.repo_registry else None,
        github_repo_id=args.github_repo_id,
        branch=args.branch,
        poll_interval_seconds=args.status_poll_interval,
        progress_heartbeat_seconds=args.progress_heartbeat_seconds,
        timeout_seconds=args.status_timeout_seconds,
    )
    print("Wiki preparation completed.")
    return 0


def _cmd_generate_baseline(args: argparse.Namespace) -> int:
    _validate_slice_selection(args)
    if args.max_tokens < 1:
        raise ValueError("--max-tokens must be at least 1")
    if args.temperature < 0:
        raise ValueError("--temperature must be non-negative")

    tasks = load_swebench_slice(
        dataset_name=args.dataset_name,
        split=args.split,
        max_instances=args.max_instances,
        instance_ids=args.instance_id,
    )

    output_path = Path(args.output)
    _print_slice(tasks, args.dataset_name, args.split)
    print(f"Model: {args.model}")
    print(f"Bedrock region: {args.region_name}")
    print(f"Output file: {output_path.resolve()}")

    generator = BedrockPatchGenerator(
        model_name=args.model,
        region_name=args.region_name,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    predictions = generate_baseline_predictions(
        tasks=tasks,
        generator=generator,
        output_path=output_path,
        overwrite=args.overwrite,
    )
    print(f"Wrote {len(predictions)} prediction(s) to {output_path.resolve()}")
    return 0


def _cmd_generate_lighthouse(args: argparse.Namespace) -> int:
    _validate_slice_selection(args)
    if args.max_tokens < 1:
        raise ValueError("--max-tokens must be at least 1")
    if args.temperature < 0:
        raise ValueError("--temperature must be non-negative")
    if args.top_k < 1:
        raise ValueError("--top-k must be at least 1")
    if args.github_repo_id is None and not args.repo_registry:
        raise ValueError(
            "Provide either --repo-registry or --github-repo-id for Lighthouse generation."
        )

    tasks = load_swebench_slice(
        dataset_name=args.dataset_name,
        split=args.split,
        max_instances=args.max_instances,
        instance_ids=args.instance_id,
    )

    output_path = Path(args.output)
    _print_slice(tasks, args.dataset_name, args.split)
    print(f"Model: {args.model}")
    print(f"Bedrock region: {args.region_name}")
    print(f"Search service URL: {args.search_url}")
    print(f"Context source: {args.context_source}")
    if args.repo_registry:
        print(f"Repository registry: {Path(args.repo_registry).resolve()}")
    elif args.github_repo_id is not None:
        print(f"GitHub repo id override: {args.github_repo_id}")
        print(f"Branch override: {args.branch}")
    print(f"Output file: {output_path.resolve()}")

    if args.context_source == "code":
        messages = build_lighthouse_messages(
            tasks=tasks,
            search_service_url=args.search_url,
            top_k=args.top_k,
            repo_registry_path=Path(args.repo_registry) if args.repo_registry else None,
            github_repo_id=args.github_repo_id,
            branch=args.branch,
        )
    else:
        messages = build_wiki_lighthouse_messages(
            tasks=tasks,
            search_service_url=args.search_url,
            top_k=args.top_k,
            repo_registry_path=Path(args.repo_registry) if args.repo_registry else None,
            github_repo_id=args.github_repo_id,
            branch=args.branch,
        )

    generator = BedrockPatchGenerator(
        model_name=args.model,
        region_name=args.region_name,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    predictions = generate_predictions(
        tasks=tasks,
        generator=generator,
        output_path=output_path,
        overwrite=args.overwrite,
        build_user_message=lambda task: messages[task.instance_id],
        progress_label="Generating Lighthouse patch for",
    )
    print(f"Wrote {len(predictions)} prediction(s) to {output_path.resolve()}")
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    _validate_slice_selection(args)

    tasks = load_swebench_slice(
        dataset_name=args.dataset_name,
        split=args.split,
        max_instances=args.max_instances,
        instance_ids=args.instance_id,
    )

    _print_slice(tasks, args.dataset_name, args.split)
    result = evaluate_swebench_predictions(
        tasks=tasks,
        dataset_name=args.dataset_name,
        split=args.split,
        predictions_path=Path(args.predictions),
        run_id=args.run_id,
        workdir=Path(args.workdir),
        max_workers=args.max_workers,
        timeout_seconds=args.timeout_seconds,
        cache_level=args.cache_level,
    )
    print(f"Evaluation report: {result.report_path}")
    print(f"Run log directory: {result.run_log_dir}")
    return 0


def _cmd_summarize(args: argparse.Namespace) -> int:
    summary = summarize_swebench_run(
        predictions_path=Path(args.predictions),
        run_id=args.run_id,
        workdir=Path(args.workdir),
    )
    _print_run_summary(summary)
    return 0


def _cmd_show_synthetic(args: argparse.Namespace) -> int:
    family, tasks, seed = select_synthetic_tasks(
        family_name=args.family,
        task_count=args.task_count,
        task_type=args.task_type,
        seed=args.seed,
        shared_library_repo_count=args.shared_library_repo_count,
    )
    _print_synthetic_selection(
        family_name=family.config.family_name,
        family_version=family.config.family_version,
        seed=seed,
        tasks=tasks,
    )
    return 0


def _cmd_prepare_synthetic(args: argparse.Namespace) -> int:
    workspace = _prepare_selected_synthetic_workspace(args)
    _print_prepared_synthetic_workspace(workspace)
    validation_results = validate_prepared_synthetic_workspace(workspace)
    print(f"Validation report: {workspace.validation_report_path.resolve()}")
    print(f"Validated tasks: {len(validation_results)}")
    return 0


def _cmd_index_synthetic(args: argparse.Namespace) -> int:
    if args.progress_heartbeat_seconds < 1:
        raise ValueError("--progress-heartbeat-seconds must be at least 1")
    if args.wiki_progress_heartbeat_seconds < 1:
        raise ValueError("--wiki-progress-heartbeat-seconds must be at least 1")
    workspace = _prepare_selected_synthetic_workspace(args)
    _print_prepared_synthetic_workspace(workspace)
    registry_path = index_synthetic_repository(
        workspace=workspace,
        ingestion_url=args.ingestion_url,
        github_token=args.github_token,
        stream_worker_logs=args.stream_worker_logs,
        poll_interval_seconds=args.status_poll_interval,
        progress_heartbeat_seconds=args.progress_heartbeat_seconds,
        timeout_seconds=args.status_timeout_seconds,
    )
    print(f"Repository registry: {registry_path}")
    if args.skip_wiki_preparation:
        print("Skipping bundled synthetic wiki preparation.")
        return 0

    prepare_synthetic_wiki(
        workspace=workspace,
        ingestion_url=args.ingestion_url,
        poll_interval_seconds=args.wiki_poll_interval,
        progress_heartbeat_seconds=args.wiki_progress_heartbeat_seconds,
        timeout_seconds=args.wiki_timeout_seconds,
    )
    print("Synthetic wiki preparation completed.")
    return 0


def _cmd_prepare_synthetic_wiki(args: argparse.Namespace) -> int:
    if args.progress_heartbeat_seconds < 1:
        raise ValueError("--progress-heartbeat-seconds must be at least 1")
    workspace = _prepare_selected_synthetic_workspace(args)
    _print_prepared_synthetic_workspace(workspace)
    prepare_synthetic_wiki(
        workspace=workspace,
        ingestion_url=args.ingestion_url,
        poll_interval_seconds=args.status_poll_interval,
        progress_heartbeat_seconds=args.progress_heartbeat_seconds,
        timeout_seconds=args.status_timeout_seconds,
    )
    print("Synthetic wiki preparation completed.")
    return 0


def _cmd_generate_synthetic_baseline(args: argparse.Namespace) -> int:
    if args.max_tokens < 1:
        raise ValueError("--max-tokens must be at least 1")
    if args.temperature < 0:
        raise ValueError("--temperature must be non-negative")

    workspace = _prepare_selected_synthetic_workspace(args)
    output_path = Path(args.output)
    _print_prepared_synthetic_workspace(workspace)
    print(f"Model: {args.model}")
    print(f"Bedrock region: {args.region_name}")
    print(f"Output file: {output_path.resolve()}")

    generator = BedrockPatchGenerator(
        model_name=args.model,
        region_name=args.region_name,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    predictions = generate_synthetic_baseline_predictions(
        tasks=workspace.tasks,
        generator=generator,
        output_path=output_path,
        overwrite=args.overwrite,
    )
    print(f"Wrote {len(predictions)} prediction(s) to {output_path.resolve()}")
    return 0


def _cmd_generate_synthetic_lighthouse(args: argparse.Namespace) -> int:
    if args.max_tokens < 1:
        raise ValueError("--max-tokens must be at least 1")
    if args.temperature < 0:
        raise ValueError("--temperature must be non-negative")
    if args.top_k < 1:
        raise ValueError("--top-k must be at least 1")

    workspace = _prepare_selected_synthetic_workspace(args)
    output_path = Path(args.output)
    _print_prepared_synthetic_workspace(workspace)
    print(f"Model: {args.model}")
    print(f"Bedrock region: {args.region_name}")
    print(f"Search service URL: {args.search_url}")
    print(f"Context source: {args.context_source}")
    print(f"Output file: {output_path.resolve()}")

    messages = build_synthetic_lighthouse_messages(
        workspace=workspace,
        search_service_url=args.search_url,
        top_k=args.top_k,
        context_source=args.context_source,
    )
    generator = BedrockPatchGenerator(
        model_name=args.model,
        region_name=args.region_name,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    predictions = generate_synthetic_predictions_jsonl(
        tasks=workspace.tasks,
        generator=generator,
        output_path=output_path,
        overwrite=args.overwrite,
        context_source=args.context_source,
        build_user_message=lambda prepared: messages[prepared.task.task_id],
        progress_label="Generating synthetic Lighthouse patch for",
    )
    print(f"Wrote {len(predictions)} prediction(s) to {output_path.resolve()}")
    return 0


def _cmd_evaluate_synthetic(args: argparse.Namespace) -> int:
    workspace = _prepare_selected_synthetic_workspace(args)
    _print_prepared_synthetic_workspace(workspace)
    predictions_path = Path(args.predictions)
    experiment = resolve_synthetic_experiment_metadata(
        generation_model_name_or_path=_infer_generation_model_name(predictions_path),
        generation_region_name=args.generation_region_name,
        context_source=_infer_prediction_context_source(predictions_path),
        search_top_k=args.search_top_k,
        indexing_embedding_strategy=args.indexing_embedding_strategy,
        indexing_embedding_model=args.indexing_embedding_model,
        query_embedding_strategy=args.query_embedding_strategy,
        query_embedding_model=args.query_embedding_model,
        repo_root=Path.cwd(),
    )
    summary = evaluate_synthetic_predictions(
        workspace=workspace,
        predictions_path=predictions_path,
        run_id=args.run_id,
        runs_root=Path(args.runs_root),
        overwrite=args.overwrite,
        experiment=experiment,
    )
    print(f"Synthetic summary: {(summary.run_dir / 'summary.json').resolve()}")
    print(f"Synthetic run directory: {summary.run_dir.resolve()}")
    _print_synthetic_run_summary(summary)
    return 0


def _cmd_summarize_synthetic(args: argparse.Namespace) -> int:
    summary = summarize_synthetic_run(
        run_id=args.run_id,
        runs_root=Path(args.runs_root),
    )
    _print_synthetic_run_summary(summary)
    return 0


def _cmd_compare_synthetic(args: argparse.Namespace) -> int:
    runs_root = Path(args.runs_root)
    try:
        comparison = compare_synthetic_runs(
            baseline_run_id=args.baseline_run_id,
            lighthouse_run_id=args.lighthouse_run_id,
            runs_root=runs_root,
            baseline_label=args.baseline_label,
            lighthouse_label=args.lighthouse_label,
        )
    except FileNotFoundError as exc:
        available_runs = list_synthetic_run_ids(runs_root=runs_root)
        available_display = ", ".join(available_runs) if available_runs else "none"
        raise RuntimeError(
            "Synthetic comparison requires completed evaluate-synthetic runs. "
            f"Could not find one of the requested run summaries under {runs_root.resolve()}: "
            f"{exc}. Available synthetic runs: {available_display}."
        ) from exc
    _print_synthetic_comparison(comparison)
    return 0


def _cmd_run_synthetic_experiment(args: argparse.Namespace) -> int:
    if args.max_tokens < 1:
        raise ValueError("--max-tokens must be at least 1")
    if args.temperature < 0:
        raise ValueError("--temperature must be non-negative")
    if args.top_k < 1:
        raise ValueError("--top-k must be at least 1")
    if args.progress_heartbeat_seconds < 1:
        raise ValueError("--progress-heartbeat-seconds must be at least 1")
    if args.wiki_progress_heartbeat_seconds < 1:
        raise ValueError("--wiki-progress-heartbeat-seconds must be at least 1")

    if args.context_source == "all":
        result = run_synthetic_experiment_suite(
            family_name=args.family,
            task_count=args.task_count,
            task_type=args.task_type,
            seed=args.seed,
            shared_library_repo_count=args.shared_library_repo_count,
            workspace_root=Path(args.workspace_root),
            force_workspace=args.force_workspace,
            run_prefix=args.run_prefix,
            predictions_root=Path(args.predictions_root),
            runs_root=Path(args.runs_root),
            artifacts_root=Path(args.artifacts_root),
            overwrite=args.overwrite,
            validate_workspace=not args.skip_validation,
            skip_index=args.skip_index,
            skip_wiki_preparation=args.skip_wiki_preparation,
            ingestion_url=args.ingestion_url,
            search_service_url=args.search_url,
            top_k=args.top_k,
            github_token=args.github_token,
            stream_worker_logs=args.stream_worker_logs,
            index_poll_interval_seconds=args.status_poll_interval,
            index_progress_heartbeat_seconds=args.progress_heartbeat_seconds,
            index_timeout_seconds=args.status_timeout_seconds,
            wiki_poll_interval_seconds=args.wiki_poll_interval,
            wiki_progress_heartbeat_seconds=args.wiki_progress_heartbeat_seconds,
            wiki_timeout_seconds=args.wiki_timeout_seconds,
            model_name=args.model,
            region_name=args.region_name,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            indexing_embedding_strategy=args.indexing_embedding_strategy,
            indexing_embedding_model=args.indexing_embedding_model,
            query_embedding_strategy=args.query_embedding_strategy,
            query_embedding_model=args.query_embedding_model,
        )
        _print_synthetic_experiment_suite_result(result)
        return 0

    result = run_synthetic_experiment(
        family_name=args.family,
        task_count=args.task_count,
        task_type=args.task_type,
        seed=args.seed,
        shared_library_repo_count=args.shared_library_repo_count,
        workspace_root=Path(args.workspace_root),
        force_workspace=args.force_workspace,
        run_prefix=args.run_prefix,
        predictions_root=Path(args.predictions_root),
        runs_root=Path(args.runs_root),
        artifacts_root=Path(args.artifacts_root),
        overwrite=args.overwrite,
        validate_workspace=not args.skip_validation,
        skip_index=args.skip_index,
        skip_wiki_preparation=args.skip_wiki_preparation,
        ingestion_url=args.ingestion_url,
        search_service_url=args.search_url,
        context_source=args.context_source,
        top_k=args.top_k,
        github_token=args.github_token,
        stream_worker_logs=args.stream_worker_logs,
        index_poll_interval_seconds=args.status_poll_interval,
        index_progress_heartbeat_seconds=args.progress_heartbeat_seconds,
        index_timeout_seconds=args.status_timeout_seconds,
        wiki_poll_interval_seconds=args.wiki_poll_interval,
        wiki_progress_heartbeat_seconds=args.wiki_progress_heartbeat_seconds,
        wiki_timeout_seconds=args.wiki_timeout_seconds,
        model_name=args.model,
        region_name=args.region_name,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        indexing_embedding_strategy=args.indexing_embedding_strategy,
        indexing_embedding_model=args.indexing_embedding_model,
        query_embedding_strategy=args.query_embedding_strategy,
        query_embedding_model=args.query_embedding_model,
    )
    _print_synthetic_experiment_result(result)
    return 0


def _prepare_selected_synthetic_workspace(
    args: argparse.Namespace,
) -> PreparedSyntheticWorkspace:
    return prepare_synthetic_workspace(
        family_name=args.family,
        task_count=args.task_count,
        task_type=args.task_type,
        seed=args.seed,
        shared_library_repo_count=args.shared_library_repo_count,
        workspace_root=Path(args.workspace_root),
        force=args.force_workspace,
    )


def _infer_generation_model_name(predictions_path: Path) -> str:
    return _first_prediction_field(predictions_path, field_name="model_name_or_path")


def _infer_prediction_context_source(predictions_path: Path) -> str:
    return _first_prediction_field(predictions_path, field_name="context_source")


def _first_prediction_field(predictions_path: Path, *, field_name: str) -> str:
    if not predictions_path.is_file():
        return ""
    import json

    for raw_line in predictions_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            continue
        value = raw.get(field_name, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _validate_slice_selection(args: argparse.Namespace) -> None:
    if args.max_instances is not None and args.max_instances < 1:
        raise ValueError("--max-instances must be at least 1")
    if args.max_instances is not None and args.instance_id:
        raise ValueError("Use either --max-instances or --instance-id, not both.")


def _print_slice(tasks: list[SWEBenchTask], dataset_name: str, split: str) -> None:
    print(f"SWE-bench slice: {len(tasks)} instance(s) from {dataset_name} [{split}]")
    for index, task in enumerate(tasks, start=1):
        print(f"{index}. {task.instance_id}")
        print(f"   repo: {task.repo}")
        print(f"   base_commit: {task.base_commit}")
        print(f"   version: {task.version}")


def _print_run_summary(summary: HarnessRunSummary) -> None:
    print(f"Harness report: {summary.outputs.report_path}")
    print(f"Run log directory: {summary.outputs.run_log_dir}")
    print(f"Total instances: {summary.total_instances}")
    print(f"Submitted instances: {summary.submitted_instances}")
    print(f"Completed instances: {summary.completed_instances}")
    print(f"Resolved instances: {summary.resolved_instances}")
    print(f"Unresolved instances: {summary.unresolved_instances}")
    print(f"Empty patch instances: {summary.empty_patch_instances}")
    print(f"Error instances: {summary.error_instances}")

    if not summary.instances:
        print("No per-instance reports were found under the run log directory.")
        return

    print("Per-instance results:")
    for instance in summary.instances:
        print(f"- {instance.instance_id}: {instance.status}")
        print(
            f"  patch applied: {'yes' if instance.patch_successfully_applied else 'no'}"
        )
        print(
            "  FAIL_TO_PASS: "
            f"{len(instance.fail_to_pass_successes)} passed, "
            f"{len(instance.fail_to_pass_failures)} failed"
        )
        print(f"  PASS_TO_PASS failures: {len(instance.pass_to_pass_failures)}")
        for test_name in instance.fail_to_pass_failures:
            print(f"  failing FAIL_TO_PASS test: {test_name}")


def _print_synthetic_selection(
    *,
    family_name: str,
    family_version: str,
    seed: int,
    tasks,
) -> None:
    print(f"Synthetic family: {family_name} [v{family_version}]")
    print(f"Selected tasks: {len(tasks)}")
    print(f"Selection seed: {seed}")
    for index, task in enumerate(tasks, start=1):
        print(f"{index}. {task.task_id}")
        print(f"   type: {task.task_type}")
        print(f"   consumer repo: {task.repo_a_name}")
        print(f"   provider repo: {task.repo_b_name}")
        print(f"   pytest targets: {', '.join(task.pytest_targets)}")


def _print_prepared_synthetic_workspace(workspace: PreparedSyntheticWorkspace) -> None:
    _print_synthetic_selection(
        family_name=workspace.family.config.family_name,
        family_version=workspace.family.config.family_version,
        seed=workspace.seed,
        tasks=tuple(prepared.task for prepared in workspace.tasks),
    )
    shared_repo = shared_resolved_repository(workspace)
    print(f"Workspace directory: {workspace.workspace_dir.resolve()}")
    print(f"Shared provider repo: {shared_repo.full_name}")
    print(f"Shared provider repo id: {shared_repo.github_repo_id}")
    print(f"Shared provider repo path: {workspace.repo_b_path.resolve()}")
    print(f"Repository registry: {workspace.repo_registry_path.resolve()}")


def _print_synthetic_run_summary(summary: SyntheticRunSummary) -> None:
    print(f"Synthetic run directory: {summary.run_dir.resolve()}")
    print(f"Family: {summary.family_name} [v{summary.family_version}]")
    print(f"Run id: {summary.run_id}")
    _print_synthetic_experiment_metadata(summary)
    print(f"Total instances: {summary.total_instances}")
    print(f"Submitted instances: {summary.submitted_instances}")
    print(f"Completed instances: {summary.completed_instances}")
    print(f"Resolved instances: {summary.resolved_instances}")
    print(f"Unresolved instances: {summary.unresolved_instances}")
    print(f"Empty patch instances: {summary.empty_patch_instances}")
    print(f"Error instances: {summary.error_instances}")
    print("Per-task results:")
    for instance in summary.instances:
        print(f"- {instance.task_id}: {instance.status}")
        print(f"  context source: {instance.context_source}")
        print(
            "  FAIL_TO_PASS: "
            f"{len(instance.fail_to_pass_successes)} passed, "
            f"{len(instance.fail_to_pass_failures)} failed"
        )
        print(
            f"  patch applied: {'yes' if instance.patch_successfully_applied else 'no'}"
        )
        if instance.patch_apply_error:
            print(f"  patch error: {instance.patch_apply_error}")
        for test_name in instance.fail_to_pass_failures:
            print(f"  failing FAIL_TO_PASS test: {test_name}")


def _print_synthetic_comparison(comparison: SyntheticRunComparison) -> None:
    print(render_synthetic_comparison_tables(comparison))


def _print_synthetic_experiment_result(result: SyntheticExperimentResult) -> None:
    _print_prepared_synthetic_workspace(result.workspace)
    print(f"Experiment report: {result.report_path.resolve()}")
    print(f"Comparison text: {result.comparison_text_path.resolve()}")
    print(f"Comparison JSON: {result.comparison_json_path.resolve()}")
    print(f"Baseline predictions: {result.baseline_predictions_path.resolve()}")
    print(f"Lighthouse predictions: {result.lighthouse_predictions_path.resolve()}")
    print("")
    _print_synthetic_comparison(result.comparison)


def _print_synthetic_experiment_suite_result(
    result: SyntheticExperimentSuiteResult,
) -> None:
    _print_prepared_synthetic_workspace(result.workspace)
    print(f"Experiment report: {result.report_path.resolve()}")
    print(f"Score table: {result.score_text_path.resolve()}")
    print(f"Score JSON: {result.score_json_path.resolve()}")
    print(f"Baseline predictions: {result.baseline_predictions_path.resolve()}")
    for label in ("code", "wiki", "code+wiki"):
        predictions_path = result.lighthouse_predictions_paths.get(label)
        if predictions_path is not None:
            print(f"{label.capitalize()} predictions: {predictions_path.resolve()}")
    print("")
    print("Scores")
    print(render_synthetic_score_table(result.score_rows))


def _print_synthetic_experiment_metadata(summary: SyntheticRunSummary) -> None:
    experiment = summary.experiment
    if experiment.generation_model_name_or_path:
        print(f"Generation model: {experiment.generation_model_name_or_path}")
    if experiment.generation_region_name:
        print(f"Generation region: {experiment.generation_region_name}")
    if experiment.indexing_embedding.strategy or experiment.indexing_embedding.model:
        print(
            "Index embedding: "
            f"{experiment.indexing_embedding.strategy or 'unknown'} / "
            f"{experiment.indexing_embedding.model or 'unknown'}"
        )
    if experiment.query_embedding.strategy or experiment.query_embedding.model:
        print(
            "Query embedding: "
            f"{experiment.query_embedding.strategy or 'unknown'} / "
            f"{experiment.query_embedding.model or 'unknown'}"
        )
    if experiment.context_source:
        print(f"Context source: {experiment.context_source}")
    if experiment.search_top_k is not None:
        print(f"Search top-k: {experiment.search_top_k}")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "show-slice":
        return _cmd_show_slice(args)
    if args.command == "show-synthetic":
        return _cmd_show_synthetic(args)
    if args.command == "prepare-images":
        return _cmd_prepare_images(args)
    if args.command == "prepare-synthetic":
        return _cmd_prepare_synthetic(args)
    if args.command == "index-repos":
        return _cmd_index_repos(args)
    if args.command == "index-synthetic":
        return _cmd_index_synthetic(args)
    if args.command == "prepare-wiki":
        return _cmd_prepare_wiki(args)
    if args.command == "prepare-synthetic-wiki":
        return _cmd_prepare_synthetic_wiki(args)
    if args.command == "generate-baseline":
        return _cmd_generate_baseline(args)
    if args.command == "generate-synthetic-baseline":
        return _cmd_generate_synthetic_baseline(args)
    if args.command == "generate-lighthouse":
        return _cmd_generate_lighthouse(args)
    if args.command == "generate-synthetic-lighthouse":
        return _cmd_generate_synthetic_lighthouse(args)
    if args.command == "evaluate":
        return _cmd_evaluate(args)
    if args.command == "evaluate-synthetic":
        return _cmd_evaluate_synthetic(args)
    if args.command == "summarize":
        return _cmd_summarize(args)
    if args.command == "summarize-synthetic":
        return _cmd_summarize_synthetic(args)
    if args.command == "compare-synthetic":
        return _cmd_compare_synthetic(args)
    if args.command == "run-synthetic-experiment":
        return _cmd_run_synthetic_experiment(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
