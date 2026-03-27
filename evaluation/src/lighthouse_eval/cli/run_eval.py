from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import yaml


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_config(path: Path):
    from lighthouse_eval.config import DatasetConfig, EvalConfig

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if "dataset" in raw and isinstance(raw["dataset"], dict):
        raw["dataset"] = DatasetConfig(**raw["dataset"])
    return EvalConfig(**raw)


def _load_index_registry(config, config_path: Path) -> dict[str, dict]:
    metadata_path = config.metadata.get("index_registry")
    if metadata_path:
        path = Path(str(metadata_path))
        if not path.is_absolute():
            path = (config_path.parent / path).resolve()
    elif config.dataset.path:
        path = Path(config.dataset.path) / "index_registry.json"
    else:
        return {}

    if not path.exists():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def _task_repo_slug(task_metadata: dict[str, object]) -> str | None:
    for key in ("repo", "repo_name", "full_name"):
        value = task_metadata.get(key)
        if isinstance(value, str) and "/" in value:
            return value
    return None


def _inject_repo_ids_from_registry(
    config,
    dataset,
    registry: dict[str, dict],
    *,
    logger: logging.Logger,
) -> None:
    if not registry:
        return

    lighthouse_enabled = any(
        provider == "lighthouse" or provider.startswith("lighthouse:")
        for provider in config.context_providers
    )

    missing = 0
    for task in dataset.tasks:
        repo_slug = _task_repo_slug(task.metadata)
        entry = registry.get(repo_slug or "")
        if not entry:
            if lighthouse_enabled:
                missing += 1
            continue
        task.metadata["github_repo_id"] = entry.get("github_repo_id")
        task.metadata["branch"] = entry.get("branch", "main")

    if lighthouse_enabled and missing:
        logger.warning(
            "%d task(s) missing github_repo_id after registry injection; "
            "lighthouse provider will return empty context for those tasks.",
            missing,
        )


def _cmd_run(args: argparse.Namespace) -> None:
    from lighthouse_eval.datasets.adapters import get_adapter
    from lighthouse_eval.reporting import EvalReport
    from lighthouse_eval.runner import run_evaluation, save_results

    config = _load_config(args.config)
    log = logging.getLogger("run_eval")
    log.info("Loaded config from %s", args.config)
    log.info(
        "  models=%s  providers=%s  adapter=%s  num_runs=%d",
        config.models,
        config.context_providers,
        config.dataset.adapter,
        config.num_runs,
    )

    adapter_cls = get_adapter(config.dataset.adapter)
    adapter = adapter_cls()
    adapter_config = config.dataset.model_dump()
    adapter_config.update(adapter_config.pop("options", {}))
    dataset = adapter.load(adapter_config)
    registry = _load_index_registry(config, args.config)
    _inject_repo_ids_from_registry(config, dataset, registry, logger=log)
    log.info("Dataset loaded: %s (%d tasks)", dataset.name, len(dataset.tasks))

    if config.dataset.max_instances is not None:
        dataset.tasks = dataset.tasks[: config.dataset.max_instances]
        log.info("  capped to %d tasks", len(dataset.tasks))

    if args.dry_run:
        log.info("Dry run — printing first task and exiting")
        if dataset.tasks:
            task = dataset.tasks[0]
            log.info(
                "  id=%s  evaluator=%s  output=%s",
                task.id,
                task.evaluator_kind,
                task.output_format,
            )
            log.info("  description=%s", task.description[:120])
        return

    results = asyncio.run(run_evaluation(config, dataset, adapter=adapter))

    results_path = save_results(results, config.output_dir)
    log.info("Results written to %s", results_path)

    report = EvalReport(results)
    report.save_json(config.output_dir / "report.json")
    report.save_markdown(config.output_dir / "report.md")
    log.info("Reports written to %s", config.output_dir)


def _cmd_report(args: argparse.Namespace) -> None:
    from lighthouse_eval.reporting import EvalReport
    from lighthouse_eval.runner import load_results

    log = logging.getLogger("run_eval")
    results = load_results(args.results)
    log.info("Loaded %d results from %s", len(results), args.results)

    report = EvalReport(results)
    out_dir = args.results.parent
    report.save_json(out_dir / "report.json")
    report.save_markdown(out_dir / "report.md")
    log.info("Reports written to %s", out_dir)

    for summary in report.test_execution:
        print(
            f"[test_exec] {summary.comparability_class} | {summary.model} | "
            f"{summary.context_provider} | pass_rate={summary.mean_pass_rate:.4f} "
            f"± {summary.stddev_pass_rate:.4f}"
        )
    for summary in report.match:
        em = (
            f"em={summary.exact_match_rate:.4f}"
            if summary.exact_match_rate is not None
            else ""
        )
        es = (
            f"edit_sim={summary.mean_edit_similarity:.4f}"
            if summary.mean_edit_similarity is not None
            else ""
        )
        print(
            f"[match] {summary.comparability_class} | {summary.model} | "
            f"{summary.context_provider} | {em} {es}"
        )
    for summary in report.retrieval:
        pk = (
            f"P@{summary.k}={summary.mean_precision_at_k:.4f}"
            if summary.mean_precision_at_k is not None
            else ""
        )
        print(f"[retrieval] {summary.comparability_class} | {summary.context_provider} | {pk}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Lighthouse evaluation framework CLI")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run an evaluation from a YAML config")
    run_p.add_argument("--config", "-c", type=Path, required=True, help="Path to YAML config file")
    run_p.add_argument("--dry-run", action="store_true", help="Load dataset and exit")

    report_p = sub.add_parser("report", help="Generate reports from existing results")
    report_p.add_argument(
        "--results", "-r", type=Path, required=True, help="Path to results JSONL"
    )

    args = parser.parse_args()
    _setup_logging(args.verbose)

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "report":
        _cmd_report(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
