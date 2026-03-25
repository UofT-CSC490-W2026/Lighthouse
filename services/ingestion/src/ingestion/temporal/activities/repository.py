from __future__ import annotations

from temporalio import activity

from ...utilities.config import IngestionSettings
from ...utilities.services import RepositoryService
from .helpers import make_db
from .inputs import EnsureRepoInput


@activity.defn
async def ensure_repository_record(input: EnsureRepoInput) -> str:
    """Upsert a Repository row and return its id."""
    settings = IngestionSettings()
    db = make_db(settings)
    try:
        svc = RepositoryService(db)
        return svc.ensure(input.github_repo_id, input.repo_url, input.full_name)
    finally:
        db.close()
