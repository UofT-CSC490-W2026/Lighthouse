import pytest
from pydantic import ValidationError

from shared.schemas.ingestion import (
    BranchStatus,
    IndexAcceptedResponse,
    IndexRequest,
    IndexStatusResponse,
    RepoIndexRequest,
)


# ── RepoIndexRequest ──────────────────────────────────────────────


@pytest.mark.unit
def test_repo_index_request_defaults():
    req = RepoIndexRequest(github_repo_id=1, repo_url="https://github.com/a/b", full_name="a/b")
    assert req.branches == ["main"]
    assert req.github_token is None


# ── IndexRequest ──────────────────────────────────────────────────


@pytest.mark.unit
def test_index_request_requires_repositories():
    with pytest.raises(ValidationError):
        IndexRequest()  # type: ignore[call-arg]


@pytest.mark.unit
def test_index_request_with_repositories():
    repo = RepoIndexRequest(github_repo_id=1, repo_url="https://github.com/a/b", full_name="a/b")
    req = IndexRequest(repositories=[repo])
    assert len(req.repositories) == 1


# ── IndexAcceptedResponse ─────────────────────────────────────────


@pytest.mark.unit
def test_index_accepted_response_status_default():
    resp = IndexAcceptedResponse(workflow_ids=["wf-1"])
    assert resp.status == "accepted"


# ── BranchStatus ──────────────────────────────────────────────────


@pytest.mark.unit
def test_branch_status_all_fields():
    bs = BranchStatus(
        branch_name="main",
        status="indexed",
        last_indexed_commit="abc123",
        indexed_at="2025-01-01T00:00:00Z",
    )
    assert bs.branch_name == "main"
    assert bs.status == "indexed"
    assert bs.last_indexed_commit == "abc123"
    assert bs.indexed_at == "2025-01-01T00:00:00Z"


# ── IndexStatusResponse ──────────────────────────────────────────


@pytest.mark.unit
def test_index_status_response_all_fields():
    bs = BranchStatus(branch_name="main", status="indexed")
    resp = IndexStatusResponse(github_repo_id=42, branches=[bs])
    assert resp.github_repo_id == 42
    assert len(resp.branches) == 1
    assert resp.branches[0].branch_name == "main"
