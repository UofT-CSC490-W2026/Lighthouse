"""Dataset loading utilities for YAML-based local datasets.

Expected directory layout::

    datasets/my_dataset/
      dataset.yaml          # Dataset metadata + task list
      tasks/
        task_001/
          prompt.md          # Task description (plain text or markdown)
          workspace/         # Source files for the task
          tests/             # Test files (for test_execution tasks)
          expected/          # Optional: expected output files
          context/           # Optional: oracle context snippets
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from lighthouse_eval.datasets.schema import (
    ContextSnippetRef,
    Dataset,
    EvaluatorKind,
    MatchSpec,
    OutputFormat,
    RetrievalSpec,
    Task,
    TaskProvenance,
    TestSpec,
)

log = logging.getLogger(__name__)


def load_yaml_dataset(
    dataset_path: Path,
    *,
    source_dataset: str = "custom",
    transform_version: str = "1.0.0",
) -> Dataset:
    """Load a dataset from a YAML directory structure."""
    meta_path = dataset_path / "dataset.yaml"
    if not meta_path.exists():
        raise FileNotFoundError(f"Dataset metadata not found: {meta_path}")

    meta: dict[str, Any] = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    ds_name = meta.get("name", dataset_path.name)
    source = meta.get("source_dataset", source_dataset)
    version = meta.get("transform_version", transform_version)

    default_evaluator = meta.get("evaluator_kind", "test_execution")
    default_output = meta.get("output_format", "file")

    tasks: list[Task] = []
    tasks_dir = dataset_path / "tasks"

    if "tasks" in meta and isinstance(meta["tasks"], list):
        for task_def in meta["tasks"]:
            tasks.append(
                _load_inline_task(task_def, dataset_path, source, version, default_evaluator, default_output)
            )
    elif tasks_dir.is_dir():
        for task_dir in sorted(tasks_dir.iterdir()):
            if task_dir.is_dir():
                tasks.append(
                    _load_dir_task(task_dir, source, version, default_evaluator, default_output)
                )

    log.info("Loaded %d tasks from %s", len(tasks), dataset_path)
    return Dataset(name=ds_name, tasks=tasks, metadata=meta.get("metadata", {}))


def _load_dir_task(
    task_dir: Path,
    source: str,
    version: str,
    default_evaluator: str,
    default_output: str,
) -> Task:
    """Load a single task from a directory."""
    task_id = task_dir.name

    prompt_path = task_dir / "prompt.md"
    if not prompt_path.exists():
        prompt_path = task_dir / "prompt.txt"
    description = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""

    task_meta_path = task_dir / "task.yaml"
    task_meta: dict[str, Any] = {}
    if task_meta_path.exists():
        task_meta = yaml.safe_load(task_meta_path.read_text(encoding="utf-8")) or {}

    evaluator_kind = EvaluatorKind(task_meta.get("evaluator_kind", default_evaluator))
    output_format = OutputFormat(task_meta.get("output_format", default_output))
    target_files = task_meta.get("target_files", [])

    workspace_path = task_dir / "workspace"
    if not workspace_path.is_dir():
        workspace_path = None

    test_spec = None
    tests_dir = task_dir / "tests"
    if tests_dir.is_dir() and evaluator_kind == EvaluatorKind.test_execution:
        test_paths = sorted(tests_dir.glob("test_*.py"))
        test_spec = TestSpec(
            test_paths=test_paths,
            test_commands=task_meta.get("test_commands", []),
            execution_backend=task_meta.get("execution_backend", "local_pytest"),
            docker_image=task_meta.get("docker_image"),
            timeout_seconds=task_meta.get("timeout_seconds", 300),
        )

    match_spec = None
    expected_dir = task_dir / "expected"
    if evaluator_kind == EvaluatorKind.match:
        gt: dict[str, str] = {}
        if expected_dir.is_dir():
            for f in expected_dir.iterdir():
                if f.is_file():
                    gt[f.name] = f.read_text(encoding="utf-8")
        if "ground_truth" in task_meta:
            gt.update(task_meta["ground_truth"])
        match_spec = MatchSpec(
            ground_truth=gt,
            metric=task_meta.get("metric", "exact_match"),
        )

    retrieval_spec = None
    if evaluator_kind == EvaluatorKind.retrieval_diagnostic and "retrieval_spec" in task_meta:
        rs = task_meta["retrieval_spec"]
        retrieval_spec = RetrievalSpec(
            ground_truth_snippets=[
                ContextSnippetRef(**s) for s in rs.get("ground_truth_snippets", [])
            ],
            gold_indices=rs.get("gold_indices", []),
            metric=rs.get("metric", "precision_at_k"),
            k=rs.get("k", 10),
        )

    oracle_context: list[ContextSnippetRef] = []
    context_dir = task_dir / "context"
    if context_dir.is_dir():
        for f in sorted(context_dir.iterdir()):
            if f.is_file() and f.suffix in (".py", ".md", ".txt"):
                oracle_context.append(
                    ContextSnippetRef(
                        file_path=f.name,
                        content=f.read_text(encoding="utf-8"),
                    )
                )

    comparability_class = task_meta.get(
        "comparability_class",
        f"{source}:{evaluator_kind.value}",
    )

    return Task(
        id=f"{source}:{task_id}",
        provenance=TaskProvenance(
            source_dataset=source,
            source_instance_id=task_id,
            transform_version=version,
            comparability_class=comparability_class,
        ),
        evaluator_kind=evaluator_kind,
        output_format=output_format,
        description=description,
        workspace_path=workspace_path,
        target_files=target_files,
        test_spec=test_spec,
        match_spec=match_spec,
        retrieval_spec=retrieval_spec,
        oracle_context=oracle_context,
        metadata=task_meta.get("metadata", {}),
    )


def _load_inline_task(
    task_def: dict[str, Any],
    dataset_path: Path,
    source: str,
    version: str,
    default_evaluator: str,
    default_output: str,
) -> Task:
    """Load a task defined inline in dataset.yaml."""
    task_id = task_def.get("id", "inline_task")
    evaluator_kind = EvaluatorKind(task_def.get("evaluator_kind", default_evaluator))
    output_format = OutputFormat(task_def.get("output_format", default_output))

    workspace_rel = task_def.get("workspace_path")
    workspace_path = (dataset_path / workspace_rel) if workspace_rel else None

    test_spec = None
    if "test_spec" in task_def:
        test_spec = TestSpec(**task_def["test_spec"])

    match_spec = None
    if "match_spec" in task_def:
        match_spec = MatchSpec(**task_def["match_spec"])

    retrieval_spec = None
    if "retrieval_spec" in task_def:
        rs = task_def["retrieval_spec"]
        retrieval_spec = RetrievalSpec(
            ground_truth_snippets=[
                ContextSnippetRef(**s) for s in rs.get("ground_truth_snippets", [])
            ],
            gold_indices=rs.get("gold_indices", []),
            metric=rs.get("metric", "precision_at_k"),
            k=rs.get("k", 10),
        )

    oracle_context = [
        ContextSnippetRef(**s) for s in task_def.get("oracle_context", [])
    ]

    comparability_class = task_def.get(
        "comparability_class",
        f"{source}:{evaluator_kind.value}",
    )

    return Task(
        id=f"{source}:{task_id}",
        provenance=TaskProvenance(
            source_dataset=source,
            source_instance_id=task_id,
            transform_version=version,
            comparability_class=comparability_class,
        ),
        evaluator_kind=evaluator_kind,
        output_format=output_format,
        description=task_def.get("description", ""),
        workspace_path=workspace_path,
        target_files=task_def.get("target_files", []),
        test_spec=test_spec,
        match_spec=match_spec,
        retrieval_spec=retrieval_spec,
        oracle_context=oracle_context,
        metadata=task_def.get("metadata", {}),
    )
