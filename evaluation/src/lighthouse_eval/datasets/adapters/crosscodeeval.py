"""CrossCodeEval adapter — loads the Python split from CrossCodeEval.

CrossCodeEval tests cross-file code completion: given ~100 lines of
in-file context, predict 1-2 lines that depend on cross-file symbols.
The dataset provides ground-truth cross-file context per retrieval method.

Source: amazon-science/cceval (GitHub, JSONL format).
Only the Python split is loaded (hardcoded).

Config options:
    source: path to local cceval data dir or HuggingFace ID
    split: JSONL file name or HF split (default: "python")
    max_instances: cap the number of tasks loaded
    retrieval_method: which cross-file context to use as oracle
                      (default: "bm25", options vary by dataset version)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
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
from lighthouse_eval.execution.evaluators.match import ExactMatchEvaluator

log = logging.getLogger(__name__)

_TRANSFORM_VERSION = "1.0.0"


@register("crosscodeeval")
class CrossCodeEvalAdapter:
    """Loads CrossCodeEval Python split into the canonical Task schema."""

    name = "crosscodeeval"
    transform_version = _TRANSFORM_VERSION

    def load(self, config: dict[str, Any]) -> Dataset:
        source = config.get("source", config.get("path"))
        max_instances = config.get("max_instances")
        retrieval_method = config.get("retrieval_method", "bm25")

        rows = self._load_rows(source, config)

        tasks: list[Task] = []
        for i, row in enumerate(rows):
            if max_instances and i >= max_instances:
                break
            task = self._row_to_task(row, retrieval_method)
            if task is not None:
                tasks.append(task)

        log.info("Loaded %d CrossCodeEval tasks", len(tasks))
        return Dataset(name="crosscodeeval:python", tasks=tasks)

    def _load_rows(self, source: str | None, config: dict[str, Any]) -> list[dict]:
        if source and Path(source).is_dir():
            return self._load_from_jsonl(Path(source), config)
        return self._load_from_hf(source, config)

    def _load_from_jsonl(self, root: Path, config: dict[str, Any]) -> list[dict]:
        split = config.get("split", "python")
        candidates = [
            root / f"{split}.jsonl",
            root / f"line_completion_{split}.jsonl",
            root / "line_completion" / f"{split}.jsonl",
        ]
        for path in candidates:
            if path.exists():
                rows = []
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
                return rows
        raise FileNotFoundError(
            f"Could not find CrossCodeEval JSONL for Python in {root}. "
            f"Tried: {[str(c) for c in candidates]}"
        )

    def _load_from_hf(self, source: str | None, config: dict[str, Any]) -> list[dict]:
        from datasets import load_dataset

        hf_id = source or "amazon-science/cceval"
        split = config.get("split", "test")
        log.info("Loading CrossCodeEval from HuggingFace: %s [%s]", hf_id, split)
        ds = load_dataset(hf_id, split=split)
        return [
            row for row in ds
            if row.get("language", "python") == "python"
        ]

    def _row_to_task(
        self, row: dict[str, Any], retrieval_method: str
    ) -> Task | None:
        task_id = row.get("task_id", row.get("id", ""))
        if not task_id:
            return None

        prompt = row.get("prompt", "")
        ground_truth = row.get("groundtruth", row.get("ground_truth", ""))

        oracle_context: list[ContextSnippetRef] = []
        cross_file_ctx = row.get("crossfile_context", {})
        if isinstance(cross_file_ctx, dict):
            ctx_list = cross_file_ctx.get(retrieval_method, [])
        elif isinstance(cross_file_ctx, list):
            ctx_list = cross_file_ctx
        else:
            ctx_list = []

        for ctx in ctx_list:
            if isinstance(ctx, dict):
                oracle_context.append(ContextSnippetRef(
                    file_path=ctx.get("path", ctx.get("filename", "unknown")),
                    content=ctx.get("snippet", ctx.get("content", "")),
                    start_line=ctx.get("start_line"),
                    end_line=ctx.get("end_line"),
                ))

        description = (
            f"Complete the following Python code.\n\n"
            f"```python\n{prompt}\n```\n\n"
            f"Provide ONLY the completion (the next line(s) of code)."
        )

        return Task(
            id=f"crosscodeeval:{task_id}",
            provenance=TaskProvenance(
                source_dataset="crosscodeeval",
                source_instance_id=str(task_id),
                transform_version=self.transform_version,
                comparability_class="crosscodeeval:match",
            ),
            evaluator_kind=EvaluatorKind.match,
            output_format=OutputFormat.completion,
            description=description,
            target_files=[],
            match_spec=MatchSpec(
                ground_truth={"_completion": ground_truth},
                metric="exact_match",
                strip_whitespace=True,
            ),
            oracle_context=oracle_context,
            metadata={
                "prompt": prompt,
                "retrieval_method": retrieval_method,
            },
        )

    def get_evaluator(self):
        return ExactMatchEvaluator()

    def get_oracle_provider(self) -> ContextProvider | None:
        return StaticProvider(name="static:oracle")

    def get_repos(self, config: dict[str, Any]) -> list[RepoInfo]:
        rows = self._load_rows(config.get("source", config.get("path")), config)
        github_token = config.get("github_token")
        default_branches = config.get("branches", ["main"])

        repo_names: set[str] = set()
        for row in rows:
            for key in ("repo", "repo_name", "repository", "project"):
                value = str(row.get(key, "")).strip()
                if "/" in value:
                    repo_names.add(value)
                    break

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
