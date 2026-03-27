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
from eval.predictions import generate_baseline_predictions


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


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "show-slice":
        return _cmd_show_slice(args)
    if args.command == "prepare-images":
        return _cmd_prepare_images(args)
    if args.command == "generate-baseline":
        return _cmd_generate_baseline(args)
    if args.command == "evaluate":
        return _cmd_evaluate(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
