from datetime import datetime, timezone
from uuid import UUID

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_api_key
from app.core.session import is_session_revoked, read_session_token
from app.db.session import get_db
from app.models.workspace import ApiKey, Workspace

SESSION_COOKIE_NAME = "ghost_session"


async def get_workspace_from_api_key(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Workspace:
    """
    Resolves the calling workspace from `Authorization: Bearer ghost_live_...`.
    This is the only thing that scopes an ingested span/metric to a company --
    there is deliberately no per-service registration step.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or malformed Authorization header")

    raw_key = authorization.split(" ", 1)[1].strip()
    key_hash = hash_api_key(raw_key)

    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API key")

    await db.execute(
        update(ApiKey).where(ApiKey.id == api_key.id).values(last_used_at=datetime.now(timezone.utc))
    )
    await db.commit()

    workspace = await db.get(Workspace, api_key.workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Workspace not found for this API key")
    return workspace


async def get_workspace_from_session(
    ghost_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> Workspace | None:
    """
    Resolves the calling workspace from the browser session cookie set by
    POST /v1/auth/login. Returns None (rather than raising) on any
    failure -- missing cookie, expired token, deleted workspace -- so
    this can be composed with bearer-key auth as a fallback rather than
    being the only path.
    """
    if not ghost_session:
        return None
    if await is_session_revoked(ghost_session):
        return None
    workspace_id = read_session_token(ghost_session)
    if workspace_id is None:
        return None
    try:
        workspace = await db.get(Workspace, UUID(workspace_id))
    except ValueError:
        return None
    return workspace


async def get_workspace_from_session_or_key(
    authorization: str | None = Header(default=None),
    ghost_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> Workspace:
    """
    For dashboard-facing read routes: accepts either a valid session
    cookie (the browser dashboard, once logged in) or a valid bearer
    API key (any other API client). Ingestion endpoints intentionally do
    NOT use this -- a session cookie makes no sense for a machine-to-
    machine OTel collector, so those stay bearer-only via
    get_workspace_from_api_key above.
    """
    session_workspace = await get_workspace_from_session(ghost_session, db)
    if session_workspace is not None:
        return session_workspace

    if authorization:
        return await get_workspace_from_api_key(authorization, db)

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated -- log in or provide an API key")