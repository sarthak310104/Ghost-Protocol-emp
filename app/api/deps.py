from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_api_key
from app.db.session import get_db
from app.models.workspace import ApiKey, Workspace


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
