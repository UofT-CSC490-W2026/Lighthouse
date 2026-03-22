"""Authentication: GitHub OAuth, session cookies, and token encryption."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request, Response

from .config import settings

SESSION_COOKIE = "lighthouse_session"
_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_URL = "https://api.github.com/user"
OAUTH_SCOPES = "read:user read:org repo"


# ── Token encryption ───────────────────────────────────


def _fernet() -> Fernet:
    key = settings.session_encryption_key.get_secret_value()
    if not key:
        raise RuntimeError("SESSION_ENCRYPTION_KEY is required")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


# ── GitHub OAuth ────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class GitHubUser:
    id: int
    login: str
    name: str | None
    avatar_url: str | None
    email: str | None


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorize_url(state: str) -> str:
    params: dict[str, str] = {
        "client_id": settings.github_oauth_client_id,
        "scope": OAUTH_SCOPES,
        "state": state,
    }
    if settings.github_oauth_callback_url:
        params["redirect_uri"] = settings.github_oauth_callback_url
    return f"{_GITHUB_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_token(code: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _GITHUB_TOKEN_URL,
            data={
                "client_id": settings.github_oauth_client_id,
                "client_secret": settings.github_oauth_client_secret.get_secret_value(),
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

    if "error" in data:
        raise ValueError(f"GitHub OAuth error: {data.get('error_description', data['error'])}")

    token = data.get("access_token")
    if not token:
        raise ValueError("No access_token in GitHub response")
    return token


async def fetch_github_user(access_token: str) -> GitHubUser:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    return GitHubUser(
        id=data["id"],
        login=data["login"],
        name=data.get("name"),
        avatar_url=data.get("avatar_url"),
        email=data.get("email"),
    )


# ── Session cookies ─────────────────────────────────────


def get_session_cookie(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def set_session_cookie(
    response: Response, session_id: str, *, max_age: int = 7 * 24 * 3600
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        max_age=max_age,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/")


# ── Auth dependency ─────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: str
    github_token: str


async def require_auth(request: Request) -> AuthContext:
    from . import db

    session_id = get_session_cookie(request)
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = await db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    token = decrypt_token(session.github_token_encrypted)
    return AuthContext(user_id=session.user_id, github_token=token)
