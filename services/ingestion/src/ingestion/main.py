from __future__ import annotations

import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from temporalio.client import Client

from .utilities import IngestionSettings
from .temporal import (
    IncrementalIndexInput,
    IncrementalIndexWorkflow,
    IndexRepoInput,
    IndexRepositoryWorkflow,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = IngestionSettings()
    app.state.settings = settings
    app.state.temporal_client = await Client.connect(settings.temporal_address)
    logger.info("Connected to Temporal at %s", settings.temporal_address)
    yield


app = FastAPI(title="Lighthouse Ingestion Service", lifespan=lifespan)


# --- Request/Response Models ---


class RepoIndexRequest(BaseModel):
    repo_url: str
    repo_id: str
    branches: list[str] = Field(default_factory=lambda: ["main"])
    github_token: str | None = None


class IndexRequest(BaseModel):
    repositories: list[RepoIndexRequest]


class BranchStatus(BaseModel):
    branch_name: str
    status: str
    last_indexed_commit: str | None = None
    indexed_at: str | None = None


class IndexStatusResponse(BaseModel):
    repo_id: str
    branches: list[BranchStatus]


class IndexAcceptedResponse(BaseModel):
    status: str = "accepted"
    workflow_ids: list[str]


# --- Endpoints ---


@app.post("/index", response_model=IndexAcceptedResponse)
async def index_repos(request: IndexRequest):
    """Kick off indexing workflows for the specified repositories."""
    temporal: Client = app.state.temporal_client
    settings: IngestionSettings = app.state.settings
    workflow_ids: list[str] = []

    for repo in request.repositories:
        workflow_id = f"index-{repo.repo_id.replace('/', '-')}"
        await temporal.start_workflow(
            IndexRepositoryWorkflow.run,
            IndexRepoInput(
                repo_url=repo.repo_url,
                repo_id=repo.repo_id,
                branches=repo.branches,
                github_token=repo.github_token,
            ),
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
        workflow_ids.append(workflow_id)
        logger.info("Started indexing workflow %s", workflow_id)

    return IndexAcceptedResponse(workflow_ids=workflow_ids)


@app.post("/webhook")
async def github_webhook(request: Request):
    """Handle GitHub push webhooks to trigger incremental re-indexing."""
    settings: IngestionSettings = app.state.settings

    # Validate signature
    body = await request.body()
    signature_header = request.headers.get("X-Hub-Signature-256", "")

    if settings.github_webhook_secret:
        if not signature_header:
            raise HTTPException(status_code=401, detail="Missing signature")

        expected = (
            "sha256="
            + hmac.new(
                settings.github_webhook_secret.encode(),
                body,
                hashlib.sha256,
            ).hexdigest()
        )
        if not hmac.compare_digest(expected, signature_header):
            raise HTTPException(status_code=401, detail="Invalid signature")

    # Only handle push events
    event_type = request.headers.get("X-GitHub-Event", "")
    if event_type != "push":
        return {"status": "ignored", "event": event_type}

    payload = json.loads(body)

    # Extract push event data
    ref = payload.get("ref", "")
    if not ref.startswith("refs/heads/"):
        return {"status": "ignored", "reason": "not a branch push"}

    branch = ref.removeprefix("refs/heads/")
    repo_full_name = payload.get("repository", {}).get("full_name", "")
    before_commit = payload.get("before", "")
    after_commit = payload.get("after", "")

    if not repo_full_name or not before_commit or not after_commit:
        raise HTTPException(status_code=400, detail="Missing required webhook fields")

    # Start incremental indexing workflow
    temporal: Client = app.state.temporal_client
    workflow_id = f"incremental-{repo_full_name.replace('/', '-')}-{branch}-{after_commit[:8]}"

    await temporal.start_workflow(
        IncrementalIndexWorkflow.run,
        IncrementalIndexInput(
            repo_id=repo_full_name,
            branch=branch,
            before_commit=before_commit,
            after_commit=after_commit,
        ),
        id=workflow_id,
        task_queue=settings.temporal_task_queue,
    )

    logger.info("Started incremental indexing workflow %s", workflow_id)
    return {"status": "accepted", "workflow_id": workflow_id}


@app.get("/status/{repo_id:path}", response_model=IndexStatusResponse)
async def get_status(repo_id: str):
    """Return indexing status for all branches of a repository."""
    from db import DatabaseManager, IndexedBranch, Repository

    settings: IngestionSettings = app.state.settings
    db = DatabaseManager(settings.postgres_dsn)
    db.connect()

    try:
        with db.connection_context():
            repo = Repository.get_or_none(Repository.repo_id == repo_id)
            if repo is None:
                raise HTTPException(status_code=404, detail=f"Repository {repo_id} not found")

            branches_query = IndexedBranch.select().where(
                IndexedBranch.repository == repo
            )
            branch_statuses = [
                BranchStatus(
                    branch_name=ib.branch_name,
                    status=ib.status,
                    last_indexed_commit=ib.last_indexed_commit,
                    indexed_at=ib.indexed_at.isoformat() if ib.indexed_at else None,
                )
                for ib in branches_query
            ]

            return IndexStatusResponse(repo_id=repo_id, branches=branch_statuses)
    finally:
        db.close()


@app.get("/health")
async def health():
    return {"status": "ok"}
