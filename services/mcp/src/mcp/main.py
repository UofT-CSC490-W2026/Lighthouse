"""Lighthouse MCP service — FastAPI application."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import db
from .auth import (
    build_authorize_url,
    clear_session_cookie,
    encrypt_token,
    exchange_code_for_token,
    fetch_github_user,
    generate_state,
    get_session_cookie,
    require_auth,
    set_session_cookie,
)
from .config import settings

log = logging.getLogger(__name__)

app = FastAPI(title="Lighthouse MCP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ──────────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ── Auth routes ─────────────────────────────────────────


@app.get("/v1/auth/github", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
async def github_authorize() -> RedirectResponse:
    state = generate_state()
    url = build_authorize_url(state)
    response = RedirectResponse(url=url, status_code=307)
    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        max_age=600,
        path="/",
    )
    return response


@app.get("/v1/auth/github/callback")
async def github_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(default=""),
) -> RedirectResponse:
    expected = request.cookies.get("oauth_state")
    if expected and state != expected:
        return RedirectResponse(url=f"{settings.web_client_url}/login?error=invalid_state")

    try:
        access_token = await exchange_code_for_token(code)
        gh_user = await fetch_github_user(access_token)
    except Exception:
        log.exception("OAuth callback failed")
        return RedirectResponse(url=f"{settings.web_client_url}/login?error=oauth_failed")

    user = await db.upsert_user(
        github_id=gh_user.id,
        github_login=gh_user.login,
        display_name=gh_user.name,
        avatar_url=gh_user.avatar_url,
        email=gh_user.email,
    )

    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.session_ttl_hours)
    encrypted = encrypt_token(access_token)
    session = await db.create_session(
        user_id=user.id,
        github_token_encrypted=encrypted,
        expires_at=expires_at,
    )

    response = RedirectResponse(url=f"{settings.web_client_url}/dashboard", status_code=302)
    set_session_cookie(response, session.id, max_age=settings.session_ttl_hours * 3600)
    response.delete_cookie(key="oauth_state", path="/")
    return response


@app.get("/v1/auth/me")
async def get_current_user(request: Request) -> dict:
    auth = await require_auth(request)
    user = await db.get_user(auth.user_id)
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "User not found"})
    return {
        "id": user.id,
        "github_id": user.github_id,
        "github_login": user.github_login,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "email": user.email,
    }


@app.post("/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> Response:
    session_id = get_session_cookie(request)
    if session_id:
        await db.delete_session(session_id)
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


# ── Repo routes ─────────────────────────────────────────

_GITHUB_URL_RE = re.compile(
    r"^(?:https?://github\.com/)?([a-zA-Z0-9\-_.]+/[a-zA-Z0-9\-_.]+?)(?:\.git)?/?$"
)


class AddRepoRequest(BaseModel):
    repo_url: str = Field(..., description="GitHub repository URL or owner/repo")
    ref: str = Field(default="main", description="Branch or tag to index")


class RepoResponse(BaseModel):
    id: str
    repo_id: str
    repo_url: str
    display_name: str
    ref: str
    added_at: str
    index_status: str | None = None


def _parse_repo(repo_url: str) -> tuple[str, str]:
    match = _GITHUB_URL_RE.match(repo_url.strip())
    if not match:
        raise ValueError(f"Invalid GitHub repo URL: {repo_url}")
    repo_id = match.group(1)
    return repo_id, f"https://github.com/{repo_id}"


@app.get("/v1/user/repos", response_model=list[RepoResponse])
async def list_user_repos(request: Request) -> list[RepoResponse]:
    auth = await require_auth(request)
    repos = await db.list_repos(auth.user_id)
    return [
        RepoResponse(
            id=r.id,
            repo_id=r.repo_id,
            repo_url=r.repo_url,
            display_name=r.display_name,
            ref=r.ref,
            added_at=r.added_at.isoformat() if r.added_at else "",
            index_status=None,
        )
        for r in repos
    ]


@app.post("/v1/user/repos", response_model=RepoResponse, status_code=status.HTTP_201_CREATED)
async def add_user_repo(request: Request, body: AddRepoRequest) -> RepoResponse:
    auth = await require_auth(request)
    try:
        repo_id, normalized_url = _parse_repo(body.repo_url)
    except ValueError as e:
        return JSONResponse(status_code=422, content={"detail": str(e)})

    display_name = repo_id.split("/")[-1]
    repo = await db.add_repo(
        user_id=auth.user_id,
        repo_id=repo_id,
        repo_url=normalized_url,
        display_name=display_name,
        ref=body.ref,
    )
    return RepoResponse(
        id=repo.id,
        repo_id=repo.repo_id,
        repo_url=repo.repo_url,
        display_name=repo.display_name,
        ref=repo.ref,
        added_at=repo.added_at.isoformat() if repo.added_at else "",
        index_status=None,
    )


@app.delete("/v1/user/repos/{repo_id:path}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user_repo(request: Request, repo_id: str) -> Response:
    auth = await require_auth(request)
    deleted = await db.delete_repo(user_id=auth.user_id, repo_id=repo_id)
    if not deleted:
        return JSONResponse(status_code=404, content={"detail": f"Repo not found: {repo_id}"})
    return Response(status_code=204)
