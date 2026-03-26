from __future__ import annotations

from temporalio import activity

from ...utilities.services import RepositoryService
from .helpers import get_settings, make_db
from .inputs import EnsureRepoInput


@activity.defn
async def ensure_repository_record(input: EnsureRepoInput) -> str:
    """Upsert a Repository row and return its id."""
    settings = get_settings()
    db = make_db(settings)
    try:
        svc = RepositoryService(db)
        return svc.ensure(input.github_repo_id, input.repo_url, input.full_name)
    finally:
        db.close()
