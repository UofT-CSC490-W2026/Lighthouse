from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from lighthouse_eval.candidates.base import Completion
from lighthouse_eval.codegen.bedrock import BedrockGenerator
from lighthouse_eval.config import EvalConfig
from lighthouse_eval.context.base import ContextProvider, ContextSnippet
from lighthouse_eval.context.lighthouse import LighthouseProvider
from lighthouse_eval.context.none import NoneProvider
from lighthouse_eval.context.static import StaticProvider
from lighthouse_eval.datasets.schema import (
    Dataset,
    EvalResult,
    EvaluatorKind,
    MatchMetrics,
    NativeMetrics,
    RetrievalMetrics,
    Task,
    TestExecutionMetrics,
)
from lighthouse_eval.execution.workspace import (
    cleanup_workspace,
    create_workspace,
    resolve_evaluator,
    serialize_candidate,
)

log = logging.getLogger(__name__)


def create_generator(model_name: str, **kwargs) -> BedrockGenerator:
    """Instantiate a BedrockGenerator for *model_name* (``bedrock/<model-id>``)."""
    if not model_name.lower().startswith("bedrock/"):
        raise ValueError(
            f"Unsupported model {model_name!r}. All models must use the 'bedrock/<model-id>' prefix."
        )
    return BedrockGenerator(model_name=model_name, **kwargs)


def create_provider(
    name: str,
    config: EvalConfig,
    adapter=None,
) -> ContextProvider:
    """Instantiate a ContextProvider by name from the eval config."""
    if name == "none":
        return NoneProvider()
    if name == "lighthouse" or name.startswith("lighthouse:"):
        methods = name.split(":", 1)[1].split(",") if ":" in name else []
        return LighthouseProvider(
            search_service_url=config.search_service_url,
            methods=methods,
        )
    if name.startswith("static"):
        if adapter is not None:
            oracle = adapter.get_oracle_provider()
            if oracle is not None:
                return oracle
        return StaticProvider(name=name)
    raise ValueError(f"Unknown context provider: {name!r}")


def _normalized_score(metrics: NativeMetrics) -> float | None:
    if isinstance(metrics, TestExecutionMetrics):
        return metrics.pass_rate
    if isinstance(metrics, MatchMetrics):
        if metrics.exact_match is not None:
            return 1.0 if metrics.exact_match else 0.0
        return metrics.edit_similarity
    if isinstance(metrics, RetrievalMetrics):
        return metrics.precision_at_k


def _requires_materialized_workspace(task: Task) -> bool:
    spec = task.test_spec
    return (
        task.evaluator_kind == EvaluatorKind.test_execution
        and spec is not None
        and spec.execution_backend in {"docker_pytest", "command_sequence"}
        and task.workspace_path is None
    )


async def _run_single_generation(
    task: Task,
    generator: BedrockGenerator,
    provider: ContextProvider,
    evaluator_factory,
    run_index: int,
    model_name: str,
    provider_name: str,
) -> EvalResult:
    """Execute one (task, model, provider, run) combination."""
    if _requires_materialized_workspace(task):
        raise RuntimeError(
            f"Task {task.id} requires a materialized workspace for "
            f"execution_backend={task.test_spec.execution_backend!r}, but none is configured."
        )

    t0 = time.perf_counter()
    context: list[ContextSnippet] = await provider.get_context(task)
    candidate = await generator.generate(task, context)
    gen_ms = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    workspace = create_workspace(task)
    try:
        candidate.apply(workspace)
        evaluator = evaluator_factory(task, context)
        native_metrics = await evaluator.evaluate(task, candidate, workspace)
    finally:
        cleanup_workspace(workspace)
    eval_ms = (time.perf_counter() - t1) * 1000.0

    return EvalResult(
        task_id=task.id,
        provenance=task.provenance,
        evaluator_kind=task.evaluator_kind,
        model=model_name,
        context_provider=provider_name,
        run_index=run_index,
        native_metrics=native_metrics,
        normalized_score=_normalized_score(native_metrics),
        generated_output=serialize_candidate(candidate),
        context_used=[s.model_dump() for s in context],
        generation_latency_ms=gen_ms,
        evaluation_latency_ms=eval_ms,
    )


async def _run_single_retrieval(
    task: Task,
    provider: ContextProvider,
    run_index: int,
    provider_name: str,
) -> EvalResult:
    """Execute one retrieval-diagnostic combination without invoking an LLM."""
    t0 = time.perf_counter()
    context: list[ContextSnippet] = await provider.get_context(task)
    evaluator = resolve_evaluator(task, context)
    native_metrics = await evaluator.evaluate(task, Completion(text=""), Path("."))
    eval_ms = (time.perf_counter() - t0) * 1000.0

    return EvalResult(
        task_id=task.id,
        provenance=task.provenance,
        evaluator_kind=task.evaluator_kind,
        model=None,
        context_provider=provider_name,
        run_index=run_index,
        native_metrics=native_metrics,
        normalized_score=_normalized_score(native_metrics),
        generated_output={},
        context_used=[s.model_dump() for s in context],
        generation_latency_ms=0.0,
        evaluation_latency_ms=eval_ms,
    )


async def run_evaluation(
    config: EvalConfig,
    dataset: Dataset,
    *,
    adapter=None,
) -> list[EvalResult]:
    """Run the full evaluation matrix and return all results.

    Iterates over generation tasks on
    ``models x context_providers x tasks x num_runs`` and retrieval-diagnostic
    tasks on ``context_providers x tasks x num_runs``, respecting
    ``config.concurrency`` for parallelism.
    """
    results: list[EvalResult] = []
    sem = asyncio.Semaphore(config.concurrency)
    retrieval_tasks = [
        task
        for task in dataset.tasks
        if task.evaluator_kind == EvaluatorKind.retrieval_diagnostic
    ]
    generation_tasks = [
        task
        for task in dataset.tasks
        if task.evaluator_kind != EvaluatorKind.retrieval_diagnostic
    ]
    total_combos = (
        len(config.models)
        * len(config.context_providers)
        * len(generation_tasks)
        * config.num_runs
        + len(config.context_providers) * len(retrieval_tasks) * config.num_runs
    )
    completed = 0

    log.info(
        "Starting evaluation: %d generation task(s), %d retrieval task(s), "
        "%d model(s), %d provider(s), %d run(s) = %d total",
        len(generation_tasks),
        len(retrieval_tasks),
        len(config.models),
        len(config.context_providers),
        config.num_runs,
        total_combos,
    )

    async def _bounded(coro):
        async with sem:
            return await coro

    tasks: list[asyncio.Task] = []

    providers = {
        provider_name: create_provider(provider_name, config, adapter)
        for provider_name in config.context_providers
    }

    for model_name in config.models:
        if not generation_tasks:
            break
        generator = create_generator(model_name)
        for provider_name, provider in providers.items():
            for task in generation_tasks:
                for run_idx in range(config.num_runs):
                    coro = _run_single_generation(
                        task=task,
                        generator=generator,
                        provider=provider,
                        evaluator_factory=lambda t, ctx: resolve_evaluator(t, ctx),
                        run_index=run_idx,
                        model_name=model_name,
                        provider_name=provider_name,
                    )
                    tasks.append(asyncio.create_task(_bounded(coro)))

    for provider_name, provider in providers.items():
        for task in retrieval_tasks:
            for run_idx in range(config.num_runs):
                coro = _run_single_retrieval(
                    task=task,
                    provider=provider,
                    run_index=run_idx,
                    provider_name=provider_name,
                )
                tasks.append(asyncio.create_task(_bounded(coro)))

    for fut in asyncio.as_completed(tasks):
        try:
            result = await fut
            results.append(result)
            completed += 1
            if completed % 10 == 0 or completed == total_combos:
                log.info("Progress: %d / %d", completed, total_combos)
        except Exception:
            completed += 1
            log.exception("Evaluation failed for one combination (%d / %d)", completed, total_combos)

    log.info("Evaluation complete: %d results collected", len(results))
    return results


def save_results(results: list[EvalResult], output_dir: Path) -> Path:
    """Write results to a JSONL file and return the path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    path = output_dir / f"results_{ts}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(r.model_dump_json() + "\n")
    log.info("Results saved to %s (%d entries)", path, len(results))
    return path


def load_results(path: Path) -> list[EvalResult]:
    """Load results from a JSONL file."""
    results: list[EvalResult] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(EvalResult.model_validate_json(line))
    return results
