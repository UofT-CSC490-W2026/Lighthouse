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

SINGLE_REPO_FAMILY = "synthetic-wrong-operator"
DUAL_REPO_WIKI_FAMILY = "synthetic-doc-behavior"


@pytest.mark.unit
def test_load_synthetic_family_includes_required_task_type() -> None:
    family = load_synthetic_family()

    assert family.config.family_name == "synthetic-ab-contracts"
    assert family.config.task_type == DEFAULT_SYNTHETIC_TASK_TYPE
    assert family.config.task_count == 10
    assert len(family.tasks) == 100
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
def test_select_synthetic_tasks_uses_sequential_prefix_order() -> None:
    _, tasks, _ = select_synthetic_tasks(task_count=10, seed=999)
    assert [task.task_id for task in tasks] == [f"ab-contracts-{idx:03d}" for idx in range(1, 11)]


@pytest.mark.unit
def test_select_synthetic_tasks_rejects_unimplemented_shared_repo_topology() -> None:
    with pytest.raises(NotImplementedError):
        select_synthetic_tasks(shared_library_repo_count=2)


@pytest.mark.unit
def test_select_synthetic_tasks_accepts_full_hundred_task_slice() -> None:
    _, tasks, seed = select_synthetic_tasks(task_count=100, seed=1)

    assert seed == 1
    assert len(tasks) == 100


@pytest.mark.integration
def test_prepare_synthetic_workspace_materializes_git_repos_and_registry(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(
        task_count=2,
        seed=7,
        workspace_root=tmp_path,
    )

    assert workspace.search_repo_path.joinpath(".git").exists()
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
    family = load_synthetic_family()
    sentinel = workspace.workspace_dir / "stale.txt"
    sentinel.write_text("stale\n", encoding="utf-8")
    newest_family_mtime = max(
        path.stat().st_mtime
        for path in family.family_dir.rglob("*")
        if path.is_file()
    )
    stale_mtime = newest_family_mtime - 3600
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
    assert repo_request.repo_url == str(workspace.search_repo_path.resolve())
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


@pytest.mark.unit
def test_load_synthetic_family_loads_single_repo_wrong_operator() -> None:
    family = load_synthetic_family(SINGLE_REPO_FAMILY)

    assert family.config.family_name == "synthetic-wrong-operator"
    assert family.config.task_type == "logic_wrong_operator"
    assert family.config.shared_library_repo_count == 0
    assert family.config.task_count == 10
    assert len(family.tasks) == 10
    assert all(t.task_type == "logic_wrong_operator" for t in family.tasks)
    assert all(t.repo_b_name == "" for t in family.tasks)
    assert all(t.repo_b_id == 0 for t in family.tasks)


@pytest.mark.unit
def test_load_synthetic_family_loads_dual_repo_doc_behavior() -> None:
    family = load_synthetic_family(DUAL_REPO_WIKI_FAMILY)

    assert family.config.family_name == "synthetic-doc-behavior"
    assert family.config.task_type == "doc_behavior_mismatch"
    assert family.config.shared_library_repo_count == 1
    assert family.config.task_count == 10
    assert len(family.tasks) == 10
    assert all(t.repo_b_name == "synthetic/doclib" for t in family.tasks)
    assert "wiki" in family.config.context_modes


@pytest.mark.integration
def test_prepare_single_repo_workspace_has_no_repo_b(tmp_path) -> None:
    _, selected_tasks, _ = select_synthetic_tasks(
        family_name=SINGLE_REPO_FAMILY,
        task_count=2,
        seed=7,
    )
    expected_repo_id = min(task.repo_a_id for task in selected_tasks)

    workspace = prepare_synthetic_workspace(
        family_name=SINGLE_REPO_FAMILY,
        task_count=2,
        seed=7,
        workspace_root=tmp_path,
    )

    assert workspace.repo_b_path is None
    assert workspace.has_shared_repo is False
    assert workspace.selection_manifest_path.is_file()
    assert workspace.repo_registry_path.is_file()
    assert all(p.repo_a_path.joinpath(".git").exists() for p in workspace.tasks)
    assert workspace.search_repo_path.joinpath(".git").exists()

    registry = json.loads(workspace.repo_registry_path.read_text(encoding="utf-8"))
    assert registry == {
        "synthetic/mathkit": {
            "branch": "main",
            "github_repo_id": expected_repo_id,
        }
    }


@pytest.mark.integration
def test_prepare_dual_repo_doc_behavior_workspace(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(
        family_name=DUAL_REPO_WIKI_FAMILY,
        task_count=2,
        seed=7,
        workspace_root=tmp_path,
    )

    assert workspace.repo_b_path is not None
    assert workspace.has_shared_repo is True
    assert workspace.repo_b_path.joinpath(".git").exists()
    assert all(p.repo_a_path.joinpath(".git").exists() for p in workspace.tasks)

    registry = json.loads(workspace.repo_registry_path.read_text(encoding="utf-8"))
    assert "synthetic/doclib" in registry


@pytest.mark.unit
def test_single_repo_workspace_uses_canonical_repo_a_for_index_wiki_and_container_url(
    tmp_path,
) -> None:
    _, selected_tasks, _ = select_synthetic_tasks(
        family_name=SINGLE_REPO_FAMILY,
        task_count=1,
        seed=7,
    )
    expected_repo_id = min(task.repo_a_id for task in selected_tasks)

    workspace = prepare_synthetic_workspace(
        family_name=SINGLE_REPO_FAMILY,
        task_count=1,
        seed=7,
        workspace_root=tmp_path,
    )

    index_request = build_synthetic_index_request(workspace, github_token="tok")
    wiki_request = build_synthetic_wiki_request(workspace)

    assert len(index_request.repositories) == 1
    repo0 = index_request.repositories[0]
    assert repo0.github_repo_id == expected_repo_id
    assert repo0.full_name == "synthetic/mathkit"
    assert repo0.repo_url == str(workspace.search_repo_path.resolve())
    assert wiki_request.github_repo_id == expected_repo_id
    assert wiki_request.branch == "main"

    repo_url = synthetic_repo_url_for_container(workspace, compose_root=tmp_path)
    assert repo_url.startswith("/workspace/")
    assert repo_url.endswith("/repos/repo_a")
