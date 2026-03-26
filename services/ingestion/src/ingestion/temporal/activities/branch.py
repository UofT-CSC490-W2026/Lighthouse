from __future__ import annotations

from temporalio import activity

from ...utilities.services import BranchService
from .helpers import get_settings, make_db
from .inputs import UpdateBranchStatusInput


@activity.defn
async def update_branch_status(input: UpdateBranchStatusInput) -> str:
    """Update the IndexedBranch status."""
    settings = get_settings()
    db = make_db(settings)
    try:
        svc = BranchService(db)
        return svc.update_status(
            repository_id=input.repository_id,
            branch=input.branch,
            status=input.status,
            latest_commit=input.latest_commit,
            github_token=input.github_token,
        )
    finally:
        db.close()
