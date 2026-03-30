from __future__ import annotations

import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager

from db import DatabaseManager
from fastapi import Depends, FastAPI, HTTPException, Request
from shared.auth import verify_internal_token
from shared.schemas.ingestion import (
    BranchStatus,
    IndexAcceptedResponse,
    IndexRequest,
    IndexStatusResponse,
)
from shared.schemas.wiki import (
    GenerateWikiAcceptedResponse,
    GenerateWikiRequest,
    WikiStatusResponse,
)
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from .temporal import (
    GenerateWikiWorkflow,
    IncrementalIndexWorkflow,
    IndexBranchWorkflow,
)
from .temporal.activities import (
    GenerateWikiInput,
    IncrementalIndexInput,
    IncrementalPushSignalInput,
    IndexBranchInput,
)
from .embedding import EmbeddingStrategy
from .llm import LLMStrategy
from .utilities import IngestionSettings
from .utilities.services import RepositoryService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = IngestionSettings()
    app.state.settings = settings
    logger.info(
        "Ingestion startup: temporal=%s namespace=%s task_queue=%s postgres_configured=%s milvus_uri=%s",
        settings.temporal_address,
        settings.resolved_temporal_namespace(),
        getattr(settings, "temporal_task_queue", "<unknown>"),
        bool(settings.postgres_dsn.strip()),
        settings.milvus_uri,
    )
    logger.info("Currently using %s chunking strategy.", settings.chunker_strategy)
    logger.info("Ingestion startup: connecting to Temporal")
    app.state.temporal_client = await Client.connect(
        settings.temporal_address,
        **settings.temporal_connect_kwargs(),
    )
    logger.info(
        "Connected to Temporal at %s in namespace %s",
        settings.temporal_address,
        settings.resolved_temporal_namespace(),
    )
    yield


app = FastAPI(title="Lighthouse Ingestion Service", lifespan=lifespan)


# --- Endpoints ---


def _ensure_repository_record(
    settings: IngestionSettings,
    github_repo_id: int,
    repo_url: str,
    full_name: str,
) -> str:
    db = DatabaseManager(settings.postgres_dsn)
    db.connect()
    try:
        return RepositoryService(db).ensure(github_repo_id, repo_url, full_name)
    finally:
        db.close()


def _validate_wiki_generation_settings(settings: IngestionSettings) -> None:
    llm_strategy_value = settings.resolved_llm_strategy()

    try:
        llm_strategy = LLMStrategy(llm_strategy_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported wiki LLM strategy: {llm_strategy_value!r}",
        ) from exc

    try:
        embedding_strategy = EmbeddingStrategy(
            settings.embedding_strategy.strip().lower()
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported wiki embedding strategy: {settings.embedding_strategy!r}",
        ) from exc

    if llm_strategy == LLMStrategy.OPENAI and not settings.openai_api_key.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "Wiki generation is configured to use the OpenAI LLM provider, but "
                "OPENAI_API_KEY is not set. Set LLM_STRATEGY=bedrock or provide "
                "OPENAI_API_KEY."
            ),
        )

    if (
        embedding_strategy == EmbeddingStrategy.OPENAI
        and not settings.openai_api_key.strip()
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Wiki generation is configured to use OpenAI embeddings, but "
                "OPENAI_API_KEY is not set. Set EMBEDDING_STRATEGY=bedrock or provide "
                "OPENAI_API_KEY."
            ),
        )


@app.post(
    "/index",
    response_model=IndexAcceptedResponse,
    dependencies=[Depends(verify_internal_token)],
)
async def index_repos(request: IndexRequest):
    """Kick off indexing workflows for the specified repository branches."""
    temporal: Client = app.state.temporal_client
    settings: IngestionSettings = app.state.settings
    workflow_ids: list[str] = []

    for repo in request.repositories:
        full_name = repo.full_name.strip().lower()
        repository_id = _ensure_repository_record(
            settings=settings,
            github_repo_id=repo.github_repo_id,
            repo_url=repo.repo_url,
            full_name=full_name,
        )

        for branch in repo.branches:
            workflow_id = f"index-branch-{repo.github_repo_id}-{full_name.replace('/', '-')}-{branch}"
            try:
                await temporal.start_workflow(
                    IndexBranchWorkflow.run,
                    IndexBranchInput(
                        repository_id=repository_id,
                        github_repo_id=repo.github_repo_id,
                        repo_url=repo.repo_url,
                        full_name=full_name,
                        branch=branch,
                        github_token=repo.github_token,
                        chunker_strategy=repo.chunker_strategy
                        or settings.chunker_strategy,
                        embedding_strategy=settings.embedding_strategy,
                        llm_strategy=settings.resolved_llm_strategy(),
                    ),
                    id=workflow_id,
                    task_queue=settings.temporal_task_queue,
                )
            except WorkflowAlreadyStartedError:
                logger.info(
                    "Skipping duplicate indexing workflow for repo %s branch %s",
                    repo.github_repo_id,
                    branch,
                )
                continue

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
    repo_data = payload.get("repository", {})
    github_repo_id = repo_data.get("id")
    full_name = repo_data.get("full_name", "").lower()
    repo_url = repo_data.get("clone_url", "")
    before_commit = payload.get("before", "")
    after_commit = payload.get("after", "")

    if not github_repo_id or not full_name or not repo_url or not before_commit or not after_commit:
        raise HTTPException(status_code=400, detail="Missing required webhook fields")

    # Start incremental indexing workflow
    temporal: Client = app.state.temporal_client
    workflow_id = f"incremental-{github_repo_id}-{branch}"
    workflow_input = IncrementalIndexInput(
        github_repo_id=github_repo_id,
        full_name=full_name,
        branch=branch,
        before_commit=before_commit,
        after_commit=after_commit,
        repo_url=repo_url,
        chunker_strategy=settings.chunker_strategy,
        embedding_strategy=settings.embedding_strategy,
        llm_strategy=settings.resolved_llm_strategy(),
    )
    signal_input = IncrementalPushSignalInput(
        github_repo_id=github_repo_id,
        full_name=full_name,
        branch=branch,
        before_commit=before_commit,
        after_commit=after_commit,
        repo_url=repo_url,
        chunker_strategy=settings.chunker_strategy,
        embedding_strategy=settings.embedding_strategy,
        llm_strategy=settings.resolved_llm_strategy(),
    )

    try:
        await temporal.start_workflow(
            IncrementalIndexWorkflow.run,
            workflow_input,
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
    except WorkflowAlreadyStartedError:
        handle = temporal.get_workflow_handle(workflow_id)
        await handle.signal(IncrementalIndexWorkflow.enqueue_push, signal_input)

    logger.info("Started incremental indexing workflow %s", workflow_id)
    return {"status": "accepted", "workflow_id": workflow_id}


@app.get(
    "/status/{github_repo_id:int}",
    response_model=IndexStatusResponse,
    dependencies=[Depends(verify_internal_token)],
)
async def get_status(github_repo_id: int):
    """Return indexing status for all branches of a repository."""
    from db import DatabaseManager, IndexedBranch, Repository

    settings: IngestionSettings = app.state.settings
    db = DatabaseManager(settings.postgres_dsn)
    db.connect()

    try:
        with db.connection_context():
            repo = Repository.get_or_none(Repository.github_repo_id == github_repo_id)
            if repo is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Repository {github_repo_id} not found",
                )

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

            return IndexStatusResponse(
                github_repo_id=github_repo_id, branches=branch_statuses
            )
    finally:
        db.close()


@app.post(
    "/generate-wiki",
    response_model=GenerateWikiAcceptedResponse,
    dependencies=[Depends(verify_internal_token)],
)
async def generate_wiki(request: GenerateWikiRequest):
    """Kick off wiki generation for an already-indexed repository."""
    from db import DatabaseManager, Repository

    settings: IngestionSettings = app.state.settings
    temporal: Client = app.state.temporal_client
    _validate_wiki_generation_settings(settings)

    db = DatabaseManager(settings.postgres_dsn)
    db.connect()
    try:
        with db.connection_context():
            repo = Repository.get_or_none(
                Repository.github_repo_id == request.github_repo_id
            )
            if repo is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Repository {request.github_repo_id} not found",
                )

        workflow_id = f"wiki-{request.github_repo_id}-{request.branch}"
        await temporal.start_workflow(
            GenerateWikiWorkflow.run,
            GenerateWikiInput(
                repository_id=repo.id,
                github_repo_id=request.github_repo_id,
                full_name=repo.full_name,
                branch=request.branch,
                llm_strategy=settings.resolved_llm_strategy(),
                embedding_strategy=settings.embedding_strategy,
            ),
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
        logger.info("Started wiki generation workflow %s", workflow_id)

        return GenerateWikiAcceptedResponse(workflow_id=workflow_id)
    finally:
        db.close()


@app.get(
    "/wiki-status/{github_repo_id:int}",
    response_model=WikiStatusResponse,
    dependencies=[Depends(verify_internal_token)],
)
async def get_wiki_status(github_repo_id: int, branch: str = "main"):
    """Return the latest wiki generation status for a repository."""
    from db import DatabaseManager, Repository, WikiGeneration

    settings: IngestionSettings = app.state.settings
    db = DatabaseManager(settings.postgres_dsn)
    db.connect()

    try:
        with db.connection_context():
            repo = Repository.get_or_none(Repository.github_repo_id == github_repo_id)
            if repo is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Repository {github_repo_id} not found",
                )

            generation = (
                WikiGeneration.select()
                .where(
                    (WikiGeneration.repository == repo)
                    & (WikiGeneration.branch == branch)
                )
                .order_by(WikiGeneration.created_at.desc())
                .first()
            )

            if generation is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No wiki generation found for {github_repo_id}/{branch}",
                )

            return WikiStatusResponse(
                github_repo_id=github_repo_id,
                branch=branch,
                status=generation.status,
                wiki_title=generation.wiki_title,
                page_count=generation.page_count,
            )
    finally:
        db.close()


@app.get("/health")
async def health():
    return {"status": "ok"}
