from __future__ import annotations

import json
import os

import pytest
from shared.schemas.ingestion import IndexRequest

from eval.synthetic import (
    DEFAULT_SYNTHETIC_TASK_TYPE,
    build_synthetic_index_request,
    build_synthetic_wiki_request,
    load_synthetic_family,
    prepare_synthetic_workspace,
    select_synthetic_tasks,
    synthetic_repo_url_for_container,
)


@pytest.mark.unit
def test_load_synthetic_family_includes_required_task_type() -> None:
    family = load_synthetic_family()

    assert family.config.family_name == "synthetic-ab-contracts"
    assert family.config.task_type == DEFAULT_SYNTHETIC_TASK_TYPE
    assert family.config.task_count == 10
    assert len(family.tasks) == 10
    assert all(task.task_type == DEFAULT_SYNTHETIC_TASK_TYPE for task in family.tasks)
    assert family.tasks[0].consumer_edit_files
    assert family.tasks[0].consumer_test_files


@pytest.mark.unit
def test_select_synthetic_tasks_is_deterministic_for_seeded_subset() -> None:
    _, first_tasks, first_seed = select_synthetic_tasks(task_count=3, seed=123)
    _, second_tasks, second_seed = select_synthetic_tasks(task_count=3, seed=123)

    assert first_seed == second_seed == 123
    assert [task.task_id for task in first_tasks] == [task.task_id for task in second_tasks]


@pytest.mark.unit
def test_select_synthetic_tasks_rejects_unimplemented_shared_repo_topology() -> None:
    with pytest.raises(NotImplementedError):
        select_synthetic_tasks(shared_library_repo_count=2)


@pytest.mark.integration
def test_prepare_synthetic_workspace_materializes_git_repos_and_registry(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(
        task_count=2,
        seed=7,
        workspace_root=tmp_path,
    )

    assert workspace.repo_b_path.joinpath(".git").exists()
    assert workspace.selection_manifest_path.is_file()
    assert workspace.repo_registry_path.is_file()
    assert all(prepared.repo_a_path.joinpath(".git").exists() for prepared in workspace.tasks)

    registry = json.loads(workspace.repo_registry_path.read_text(encoding="utf-8"))
    assert registry == {
        "synthetic/providerlib": {
            "branch": "main",
            "github_repo_id": 900000001,
        }
    }


@pytest.mark.integration
def test_prepare_synthetic_workspace_refreshes_stale_materialization(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(
        task_count=1,
        seed=7,
        workspace_root=tmp_path,
    )
    sentinel = workspace.workspace_dir / "stale.txt"
    sentinel.write_text("stale\n", encoding="utf-8")
    stale_mtime = workspace.selection_manifest_path.stat().st_mtime - 3600
    os.utime(workspace.selection_manifest_path, (stale_mtime, stale_mtime))

    refreshed = prepare_synthetic_workspace(
        task_count=1,
        seed=7,
        workspace_root=tmp_path,
    )

    assert refreshed.workspace_dir == workspace.workspace_dir
    assert not sentinel.exists()
    assert refreshed.selection_manifest_path.stat().st_mtime > stale_mtime


@pytest.mark.unit
def test_build_synthetic_requests_target_shared_provider_repo(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(
        task_count=1,
        seed=11,
        workspace_root=tmp_path,
    )

    index_request = build_synthetic_index_request(workspace, github_token="token-123")
    wiki_request = build_synthetic_wiki_request(workspace)

    assert isinstance(index_request, IndexRequest)
    assert len(index_request.repositories) == 1
    repo_request = index_request.repositories[0]
    assert repo_request.github_repo_id == 900000001
    assert repo_request.full_name == "synthetic/providerlib"
    assert repo_request.repo_url == str(workspace.repo_b_path.resolve())
    assert repo_request.branches == ["main"]
    assert repo_request.github_token == "token-123"
    assert wiki_request.github_repo_id == 900000001
    assert wiki_request.branch == "main"


@pytest.mark.unit
def test_build_synthetic_index_request_accepts_repo_url_override(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(
        task_count=1,
        seed=11,
        workspace_root=tmp_path,
    )

    index_request = build_synthetic_index_request(
        workspace,
        repo_url_override="/workspace/.cache/eval/synthetic/repos/repo_b",
    )

    assert index_request.repositories[0].repo_url == "/workspace/.cache/eval/synthetic/repos/repo_b"


@pytest.mark.unit
def test_synthetic_repo_url_for_container_rewrites_under_compose_root(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(
        task_count=1,
        seed=11,
        workspace_root=tmp_path / ".cache" / "eval" / "synthetic",
    )

    repo_url = synthetic_repo_url_for_container(workspace, compose_root=tmp_path)

    assert repo_url.startswith("/workspace/")
    assert repo_url.endswith("/repos/repo_b")
