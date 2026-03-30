from __future__ import annotations

from unittest.mock import patch

import pytest

from eval.slice import SWEBenchTask, load_swebench_slice


def _fake_dataset() -> list[dict[str, str]]:
    return [
        {
            "instance_id": "django__django-11001",
            "repo": "django/django",
            "base_commit": "aaa",
            "version": "3.0",
            "problem_statement": "Django bug",
        },
        {
            "instance_id": "django__django-11002",
            "repo": "django/django",
            "base_commit": "bbb",
            "version": "3.0",
            "problem_statement": "Another Django bug",
        },
        {
            "instance_id": "sympy__sympy-20001",
            "repo": "sympy/sympy",
            "base_commit": "ccc",
            "version": "1.8",
            "problem_statement": "Sympy bug",
        },
        {
            "instance_id": "sklearn__scikit-learn-30001",
            "repo": "scikit-learn/scikit-learn",
            "base_commit": "ddd",
            "version": "0.24",
            "problem_statement": "Sklearn bug",
        },
    ]


def _patch_load_dataset(fake_data: list[dict[str, str]]):
    return patch(
        "datasets.load_dataset",
        return_value=fake_data,
    )


@pytest.mark.unit
def test_repo_filter_returns_matching_tasks() -> None:
    with _patch_load_dataset(_fake_dataset()):
        tasks = load_swebench_slice(repos=["django/django"])
    assert len(tasks) == 2
    assert all(t.repo == "django/django" for t in tasks)


@pytest.mark.unit
def test_repo_filter_case_insensitive() -> None:
    with _patch_load_dataset(_fake_dataset()):
        tasks = load_swebench_slice(repos=["Django/Django"])
    assert len(tasks) == 2


@pytest.mark.unit
def test_repo_filter_multiple_repos() -> None:
    with _patch_load_dataset(_fake_dataset()):
        tasks = load_swebench_slice(repos=["django/django", "sympy/sympy"])
    assert len(tasks) == 3


@pytest.mark.unit
def test_repo_filter_with_max_instances() -> None:
    with _patch_load_dataset(_fake_dataset()):
        tasks = load_swebench_slice(repos=["django/django"], max_instances=1)
    assert len(tasks) == 1
    assert tasks[0].instance_id == "django__django-11001"


@pytest.mark.unit
def test_repo_filter_with_instance_ids() -> None:
    with _patch_load_dataset(_fake_dataset()):
        tasks = load_swebench_slice(
            instance_ids=["django__django-11001", "sympy__sympy-20001"],
            repos=["django/django"],
        )
    assert len(tasks) == 1
    assert tasks[0].instance_id == "django__django-11001"


@pytest.mark.unit
def test_repo_filter_no_matches_raises() -> None:
    with _patch_load_dataset(_fake_dataset()):
        with pytest.raises(ValueError, match="No SWE-bench tasks matched"):
            load_swebench_slice(repos=["nonexistent/repo"])


@pytest.mark.unit
def test_repo_filter_instance_ids_no_matches_raises() -> None:
    with _patch_load_dataset(_fake_dataset()):
        with pytest.raises(ValueError, match="No SWE-bench tasks matched"):
            load_swebench_slice(
                instance_ids=["sympy__sympy-20001"],
                repos=["django/django"],
            )


@pytest.mark.unit
def test_no_filter_returns_all() -> None:
    with _patch_load_dataset(_fake_dataset()):
        tasks = load_swebench_slice()
    assert len(tasks) == 4


@pytest.mark.unit
def test_empty_repo_list_ignored() -> None:
    with _patch_load_dataset(_fake_dataset()):
        tasks = load_swebench_slice(repos=[])
    assert len(tasks) == 4
