"""RepoBench adapter — loads repobench_python_v1.1 from HuggingFace.

RepoBench tests cross-file next-line completion.  The Python split
provides ``cropped_code`` + ``import_statement`` as prompt, ``next_line``
as ground truth, and a ``context`` list with a ``gold_snippet_index``
indicating which context snippet is relevant.

Only the Python dataset is loaded (hardcoded).

Config options:
    source: HuggingFace dataset ID (default: "tianyang/repobench_python_v1.1")
    split: one of "cross_file_first", "cross_file_random", "in_file"
           (default: "cross_file_first")
    max_instances: cap the number of tasks loaded
"""

from __future__ import annotations

import logging
from typing import Any

from lighthouse_eval.context.base import ContextProvider
from lighthouse_eval.context.static import StaticProvider
from lighthouse_eval.datasets.adapters import register
from lighthouse_eval.datasets.adapters.base import RepoInfo, resolve_github_repo_id
from lighthouse_eval.datasets.schema import (
    ContextSnippetRef,
    Dataset,
    EvaluatorKind,
    MatchSpec,
    OutputFormat,
    RetrievalSpec,
    Task,
    TaskProvenance,
)
from lighthouse_eval.execution.evaluators.match import ExactMatchEvaluator

log = logging.getLogger(__name__)

_DEFAULT_SOURCE = "tianyang/repobench_python_v1.1"
_TRANSFORM_VERSION = "1.0.0"


@register("repobench")
class RepoBenchAdapter:
    """Loads RepoBench Python split into the canonical Task schema."""

    name = "repobench"
    transform_version = _TRANSFORM_VERSION

    def load(self, config: dict[str, Any]) -> Dataset:
        from datasets import load_dataset

        source = config.get("source", _DEFAULT_SOURCE)
        split = config.get("split", "cross_file_first")
        max_instances = config.get("max_instances")

        log.info("Loading RepoBench from %s [%s]", source, split)
        ds = load_dataset(source, split=split)

        tasks: list[Task] = []
        for i, row in enumerate(ds):
            if max_instances and i >= max_instances:
                break
            task = self._row_to_task(row, i, split)
            if task is not None:
                tasks.append(task)

        log.info("Loaded %d RepoBench tasks", len(tasks))
        return Dataset(name=f"repobench:{split}", tasks=tasks)

    def _row_to_task(
        self, row: dict[str, Any], index: int, split: str
    ) -> Task | None:
        cropped_code = row.get("cropped_code", "")
        import_statement = row.get("import_statement", "")
        next_line = row.get("next_line", "")
        repo_name = row.get("repo_name", "")

        if not next_line:
            return None

        instance_id = f"{split}_{index}"

        context_list = row.get("context", [])
        gold_snippet_index = row.get("gold_snippet_index")

        oracle_context: list[ContextSnippetRef] = []
        for j, ctx in enumerate(context_list):
            if isinstance(ctx, dict):
                oracle_context.append(ContextSnippetRef(
                    file_path=ctx.get("path", f"context_{j}.py"),
                    content=ctx.get("snippet", ctx.get("content", "")),
                ))
            elif isinstance(ctx, str):
                oracle_context.append(ContextSnippetRef(
                    file_path=f"context_{j}.py",
                    content=ctx,
                ))

        gold_indices = []
        if gold_snippet_index is not None:
            if isinstance(gold_snippet_index, list):
                gold_indices = gold_snippet_index
            else:
                gold_indices = [int(gold_snippet_index)]

        retrieval_spec = RetrievalSpec(
            ground_truth_snippets=[oracle_context[i] for i in gold_indices if i < len(oracle_context)],
            gold_indices=gold_indices,
            k=10,
        ) if gold_indices else None

        description = (
            f"Complete the next line of this Python file.\n\n"
            f"Import statements:\n```python\n{import_statement}\n```\n\n"
            f"Code so far:\n```python\n{cropped_code}\n```\n\n"
            f"Provide ONLY the next line of code."
        )

        return Task(
            id=f"repobench:{instance_id}",
            provenance=TaskProvenance(
                source_dataset="repobench",
                source_instance_id=instance_id,
                transform_version=self.transform_version,
                comparability_class=f"repobench:{split}:match",
            ),
            evaluator_kind=EvaluatorKind.match,
            output_format=OutputFormat.completion,
            description=description,
            target_files=[],
            match_spec=MatchSpec(
                ground_truth={"_completion": next_line},
                metric="exact_match",
                strip_whitespace=True,
            ),
            retrieval_spec=retrieval_spec,
            oracle_context=oracle_context,
            metadata={
                "repo_name": repo_name,
                "split": split,
            },
        )

    def get_evaluator(self):
        return ExactMatchEvaluator()

    def get_oracle_provider(self) -> ContextProvider | None:
        return StaticProvider(name="static:oracle")

    def get_repos(self, config: dict[str, Any]) -> list[RepoInfo]:
        from datasets import load_dataset

        source = config.get("source", _DEFAULT_SOURCE)
        split = config.get("split", "cross_file_first")
        max_instances = config.get("max_instances")
        github_token = config.get("github_token")
        default_branches = config.get("branches", ["main"])

        ds = load_dataset(source, split=split)
        repo_names: set[str] = set()
        for i, row in enumerate(ds):
            if max_instances and i >= max_instances:
                break
            value = str(row.get("repo_name", "")).strip()
            if "/" in value:
                repo_names.add(value)

        repos: list[RepoInfo] = []
        for full_name in sorted(repo_names):
            repos.append(
                RepoInfo(
                    github_repo_id=resolve_github_repo_id(full_name, github_token=github_token),
                    repo_url=f"https://github.com/{full_name}",
                    full_name=full_name,
                    branches=list(default_branches),
                )
            )
        return repos
