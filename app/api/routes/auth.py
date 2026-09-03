from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SESSION_COOKIE_NAME, get_workspace_from_session_or_key
from app.core.config import get_settings
from app.core.redis_client import get_redis
from app.core.security import hash_api_key
from app.core.session import create_session_token, revoke_session_token
from app.db.session import get_db
from app.models.workspace import ApiKey, Workspace

router = APIRouter()
settings = get_settings()


class LoginIn(BaseModel):
    # Real keys are ~44 chars ("ghost_live_" + 32 hex); 256 is a generous
    # ceiling that blocks pathological input (someone posting megabytes
    # of junk to force wasted hashing work) without ever constraining a
    # real key.
    api_key: str = Field(min_length=1, max_length=256)


async def _check_login_rate_limit(request: Request) -> None:
    """
    Per-IP sliding-ish window via a Redis counter with a fixed 60s
    expiry -- not a defense against a determined distributed attacker
    (this is self-hosted, single-process; a real edge/WAF layer is the
    right place for that), but it stops a single client from hammering
    the login endpoint and burning CPU on repeated hashing and DB
    round-trips, which is the actual cheap-to-fix risk here given the
    key space itself (128-bit random) is already infeasible to brute
    force outright.
    """
    client_ip = request.client.host if request.client else "unknown"
    key = f"login_attempts:{client_ip}"
    r = get_redis()
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, 60)
    if count > settings.ghost_login_rate_limit_per_minute:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts -- try again shortly")


@router.post("/v1/auth/login")
async def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Exchanges a workspace's API key for a browser session cookie. The
    dashboard calls this once at login; every subsequent request goes
    through the cookie, and the raw API key never needs to be stored in
    browser JS state (localStorage, etc.) where it would be vulnerable
    to XSS-based token theft.
    """
    await _check_login_rate_limit(request)

    key_hash = hash_api_key(payload.api_key)
    result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True)))
    api_key = result.scalar_one_or_none()
    if api_key is None:
        # Same generic message regardless of *why* it failed (key never
        # existed vs. revoked vs. workspace deleted) -- distinguishing
        # those cases in the response would let an attacker enumerate
        # which keys are real.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API key")

    await db.execute(
        update(ApiKey).where(ApiKey.id == api_key.id).values(last_used_at=datetime.now(timezone.utc))
    )
    await db.commit()

    workspace = await db.get(Workspace, api_key.workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API key")

    token = create_session_token(str(workspace.id))
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookies_secure,  # True whenever GHOST_ENV != "local"
        max_age=60 * 60 * 12,
        path="/",
    )
    return {"workspace_id": str(workspace.id), "name": workspace.name}


@router.post("/v1/auth/logout")
async def logout(response: Response, ghost_session: str | None = Cookie(default=None)):
    if ghost_session:
        # Actually invalidate the token server-side (see app/core/session.py),
        # not just clear the browser's copy of the cookie -- otherwise a
        # copy of the token captured before logout (e.g. via a proxy log,
        # a shared machine, a browser history/devtools artifact) would
        # stay valid for the rest of its 12-hour lifetime regardless of
        # the user having "logged out."
        await revoke_session_token(ghost_session)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"logged_out": True}


@router.get("/v1/auth/me")
async def me(workspace: Workspace = Depends(get_workspace_from_session_or_key)):
    """Lets the dashboard check 'am I still logged in' on page load without hitting a data endpoint."""
    return {"workspace_id": str(workspace.id), "name": workspace.name}