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
from eval.slice import DEFAULT_DATASET_NAME, DEFAULT_SPLIT, SWEBenchTask, load_swebench_slice

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
    if args.repo_registry:
        print(f"Repository registry: {Path(args.repo_registry).resolve()}")
    elif args.github_repo_id is not None:
        print(f"GitHub repo id override: {args.github_repo_id}")
        print(f"Branch override: {args.branch}")
    print(f"Output file: {output_path.resolve()}")

    messages = build_lighthouse_messages(
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
        print(f"  patch applied: {'yes' if instance.patch_successfully_applied else 'no'}")
        print(
            "  FAIL_TO_PASS: "
            f"{len(instance.fail_to_pass_successes)} passed, "
            f"{len(instance.fail_to_pass_failures)} failed"
        )
        print(f"  PASS_TO_PASS failures: {len(instance.pass_to_pass_failures)}")
        for test_name in instance.fail_to_pass_failures:
            print(f"  failing FAIL_TO_PASS test: {test_name}")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "show-slice":
        return _cmd_show_slice(args)
    if args.command == "prepare-images":
        return _cmd_prepare_images(args)
    if args.command == "index-repos":
        return _cmd_index_repos(args)
    if args.command == "generate-baseline":
        return _cmd_generate_baseline(args)
    if args.command == "generate-lighthouse":
        return _cmd_generate_lighthouse(args)
    if args.command == "evaluate":
        return _cmd_evaluate(args)
    if args.command == "summarize":
        return _cmd_summarize(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
