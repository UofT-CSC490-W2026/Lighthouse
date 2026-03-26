from __future__ import annotations

from pathlib import Path

from temporalio import activity

from ...utilities.git_ops import GitOperations
from .helpers import get_settings
from .inputs import GetChangedFilesInput, GitCloneFetchInput, GitCloneFetchOutput


@activity.defn
async def git_clone_or_fetch(input: GitCloneFetchInput) -> GitCloneFetchOutput:
    """Clone or fetch a repo and return the path + latest commit."""
    settings = get_settings()
    git = GitOperations(
        base_dir=settings.clone_base_dir,
        github_token=input.github_token,
    )
    repo_path = git.clone_or_fetch(input.repo_url, input.repo_dir_name, input.branch)
    latest_commit = git.get_latest_commit(repo_path, input.branch)
    return GitCloneFetchOutput(
        repo_path=str(repo_path),
        latest_commit=latest_commit,
    )


@activity.defn
async def get_changed_files(input: GetChangedFilesInput) -> list[str]:
    """Get the list of changed files between two commits."""
    settings = get_settings()
    git = GitOperations(base_dir=settings.clone_base_dir)
    repo_path = Path(input.repo_path)
    changed = git.get_changed_files(repo_path, input.before_commit, input.after_commit)
    return [str(f.relative_to(repo_path)) for f in changed]
