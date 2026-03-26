"""RepoQA adapter — loads the Search Needle Function (SNF) task.

RepoQA tests retrieval: given a large code context (~16K tokens) and a
natural-language description of a function, the model must find and
output the matching function.  Scored by BLEU against the ground-truth
function body with a pass threshold of 0.8.

Only Python repositories are loaded (hardcoded filter).

Config options:
    source: "repoqa" pip package name or HuggingFace ID (default: uses pip)
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
    Task,
    TaskProvenance,
)
from lighthouse_eval.execution.evaluators.match import BLEUEvaluator

log = logging.getLogger(__name__)

_TRANSFORM_VERSION = "1.0.0"


@register("repoqa")
class RepoQAAdapter:
    """Loads RepoQA SNF tasks (Python repos only) into the canonical Task schema."""

    name = "repoqa"
    transform_version = _TRANSFORM_VERSION

    def load(self, config: dict[str, Any]) -> Dataset:
        max_instances = config.get("max_instances")

        rows = self._load_rows(config)

        tasks: list[Task] = []
        for i, row in enumerate(rows):
            if max_instances and i >= max_instances:
                break
            task = self._row_to_task(row, i)
            if task is not None:
                tasks.append(task)

        log.info("Loaded %d RepoQA tasks", len(tasks))
        return Dataset(name="repoqa:python", tasks=tasks)

    def _load_rows(self, config: dict[str, Any]) -> list[dict]:
        source = config.get("source")
        if source and source.startswith("/"):
            return self._load_from_local(source)
        return self._load_from_hf(config)

    def _load_from_local(self, path: str) -> list[dict]:
        import json
        from pathlib import Path

        p = Path(path)
        rows = []
        for f in sorted(p.glob("*.json")) if p.is_dir() else [p]:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, list):
                rows.extend(data)
            elif isinstance(data, dict):
                rows.append(data)
        return [r for r in rows if r.get("language", "python").lower() == "python"]

    def _load_from_hf(self, config: dict[str, Any]) -> list[dict]:
        from datasets import load_dataset

        source = config.get("source", "evalplus/repoqa")
        split = config.get("split", "test")
        log.info("Loading RepoQA from HuggingFace: %s [%s]", source, split)
        ds = load_dataset(source, split=split)
        return [
            row for row in ds
            if row.get("language", "python").lower() == "python"
        ]

    def _row_to_task(self, row: dict[str, Any], index: int) -> Task | None:
        repo = row.get("repo", row.get("repo_name", f"repo_{index}"))
        func_name = row.get("func_name", row.get("needle_function", ""))
        nl_description = row.get("description", row.get("nl_description", ""))
        ground_truth = row.get("ground_truth", row.get("needle_code", ""))
        code_context = row.get("code_context", row.get("context", ""))

        if not ground_truth or not nl_description:
            return None

        instance_id = f"{repo}:{func_name}" if func_name else f"idx_{index}"

        oracle_context: list[ContextSnippetRef] = []
        if code_context:
            oracle_context.append(ContextSnippetRef(
                file_path=f"{repo}/context.py",
                content=code_context if isinstance(code_context, str) else str(code_context),
            ))

        description = (
            f"Find the Python function described below in the repository '{repo}'.\n\n"
            f"## Function description\n\n{nl_description}\n\n"
            f"Respond with ONLY the complete function implementation."
        )

        return Task(
            id=f"repoqa:{instance_id}",
            provenance=TaskProvenance(
                source_dataset="repoqa",
                source_instance_id=instance_id,
                transform_version=self.transform_version,
                comparability_class="repoqa:match",
            ),
            evaluator_kind=EvaluatorKind.match,
            output_format=OutputFormat.completion,
            description=description,
            target_files=[],
            match_spec=MatchSpec(
                ground_truth={"_completion": ground_truth},
                metric="bleu",
            ),
            oracle_context=oracle_context,
            metadata={
                "repo": repo,
                "func_name": func_name,
            },
        )

    def get_evaluator(self):
        return BLEUEvaluator()

    def get_oracle_provider(self) -> ContextProvider | None:
        return StaticProvider(name="static:oracle")

    def get_repos(self, config: dict[str, Any]) -> list[RepoInfo]:
        rows = self._load_rows(config)
        github_token = config.get("github_token")
        default_branches = config.get("branches", ["main"])

        repo_names: set[str] = set()
        for row in rows:
            value = str(row.get("repo", row.get("repo_name", ""))).strip()
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
