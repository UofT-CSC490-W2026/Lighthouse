"""SWE-bench adapter — loads SWE-bench Lite / Verified from HuggingFace.

Requires the ``swebench`` package for Docker-based evaluation and the
``datasets`` library for loading from HuggingFace.

Each instance contains a real GitHub issue + test patch.  The LLM must
produce a unified patch that fixes the bug while keeping existing tests
passing.
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
    Dataset,
    EvaluatorKind,
    OutputFormat,
    Task,
    TaskProvenance,
    TestSpec,
)
from lighthouse_eval.execution.evaluators.test_execution import PytestEvaluator

log = logging.getLogger(__name__)

_DEFAULT_SOURCE = "princeton-nlp/SWE-bench_Lite"
_TRANSFORM_VERSION = "1.0.0"


@register("swebench")
class SWEBenchAdapter:
    """Loads SWE-bench Lite or Verified and maps to the canonical Task schema.

    Config options:
        source: HuggingFace dataset ID (default: princeton-nlp/SWE-bench_Lite)
        split: dataset split (default: "test")
        max_instances: cap the number of tasks loaded
    """

    name = "swebench"
    transform_version = _TRANSFORM_VERSION

    def load(self, config: dict[str, Any]) -> Dataset:
        from datasets import load_dataset

        source = config.get("source", _DEFAULT_SOURCE)
        split = config.get("split", "test")
        max_instances = config.get("max_instances")

        log.info("Loading SWE-bench from %s [%s]", source, split)
        ds = load_dataset(source, split=split)

        tasks: list[Task] = []
        for i, row in enumerate(ds):
            if max_instances and i >= max_instances:
                break
            tasks.append(self._row_to_task(row, source))

        log.info("Loaded %d SWE-bench tasks", len(tasks))
        return Dataset(name=f"swebench:{split}", tasks=tasks)

    def _row_to_task(self, row: dict[str, Any], source: str) -> Task:
        instance_id = row["instance_id"]

        fail_to_pass = _parse_test_list(row.get("FAIL_TO_PASS", "[]"))
        pass_to_pass = _parse_test_list(row.get("PASS_TO_PASS", "[]"))

        description = (
            f"## {instance_id}\n\n"
            f"{row.get('problem_statement', '')}\n\n"
            f"Repository: {row.get('repo', '')}\n"
            f"Base commit: {row.get('base_commit', '')}\n"
            f"Version: {row.get('version', '')}"
        )

        test_spec = TestSpec(
            test_commands=["python -m pytest --tb=short -q"],
            expected_to_pass=fail_to_pass,
            expected_to_stay_passing=pass_to_pass,
            docker_image=f"swebench:{instance_id}",
            timeout_seconds=600,
        )

        return Task(
            id=f"swebench:{instance_id}",
            provenance=TaskProvenance(
                source_dataset=source,
                source_instance_id=instance_id,
                transform_version=self.transform_version,
                comparability_class="swebench:test_execution",
            ),
            evaluator_kind=EvaluatorKind.test_execution,
            output_format=OutputFormat.patch,
            description=description,
            target_files=[],
            test_spec=test_spec,
            metadata={
                "repo": row.get("repo", ""),
                "base_commit": row.get("base_commit", ""),
                "version": row.get("version", ""),
                "gold_patch": row.get("patch", ""),
                "test_patch": row.get("test_patch", ""),
            },
        )

    def get_evaluator(self):
        return PytestEvaluator()

    def get_oracle_provider(self) -> ContextProvider | None:
        return None

    def get_repos(self, config: dict[str, Any]) -> list[RepoInfo]:
        from datasets import load_dataset

        source = config.get("source", _DEFAULT_SOURCE)
        split = config.get("split", "test")
        max_instances = config.get("max_instances")
        github_token = config.get("github_token")
        default_branches = config.get("branches", ["main"])

        ds = load_dataset(source, split=split)
        repo_names: set[str] = set()
        for i, row in enumerate(ds):
            if max_instances and i >= max_instances:
                break
            repo = str(row.get("repo", "")).strip()
            if repo and "/" in repo:
                repo_names.add(repo)

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


def _parse_test_list(raw: str) -> list[str]:
    """Parse a JSON-encoded list of test identifiers."""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(t) for t in parsed]
    except (json.JSONDecodeError, TypeError):
        pass
    return []
