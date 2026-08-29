"""
Minimal provisioning + settings surface for a self-hosted deployment.
Gated by a shared admin secret (GHOST_SECRET_KEY) -- fine for a
single-operator self-hosted install, not a substitute for real admin
auth in a multi-admin setup.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.core.config import get_settings
from app.core.crypto import encrypt_secret
from app.core.security import generate_api_key, hash_api_key
from app.db.session import get_db
from app.models.workspace import ApiKey, Workspace

router = APIRouter()
settings = get_settings()


class CreateWorkspaceIn(BaseModel):
    name: str


class CreateWorkspaceOut(BaseModel):
    workspace_id: str
    api_key: str  # shown once -- this is the ingestion key, paste into the OTel collector config


class ConfigureReasoningIn(BaseModel):
    """
    Point this workspace at an optional external reasoning/analysis
    service that implements the contract this endpoint expects.
    `provider_label` is purely informational (shown in the dashboard),
    it doesn't change any behavior -- the endpoint is called the same
    way regardless of what's behind it.
    """
    reasoning_endpoint_url: str
    reasoning_api_key: str
    provider_label: str = "custom"


def _require_admin(x_admin_secret: str | None = Header(default=None)) -> None:
    if not settings.ghost_secret_key or x_admin_secret != settings.ghost_secret_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid X-Admin-Secret header")


@router.post("/v1/admin/workspaces", response_model=CreateWorkspaceOut, dependencies=[Depends(_require_admin)])
async def create_workspace(payload: CreateWorkspaceIn, db: AsyncSession = Depends(get_db)) -> CreateWorkspaceOut:
    workspace = Workspace(name=payload.name)
    db.add(workspace)
    await db.flush()

    raw_key = generate_api_key()
    db.add(ApiKey(workspace_id=workspace.id, key_hash=hash_api_key(raw_key), label="ingestion"))
    await db.commit()

    return CreateWorkspaceOut(workspace_id=str(workspace.id), api_key=raw_key)


@router.put("/v1/admin/workspaces/{workspace_id}/reasoning", dependencies=[Depends(_require_admin)])
async def configure_reasoning(workspace_id: str, payload: ConfigureReasoningIn, db: AsyncSession = Depends(get_db)):
    """
    Connects this workspace to an optional external reasoning/analysis
    endpoint. Point this at any service implementing the expected
    request/response contract.
    """
    workspace = await db.get(Workspace, uuid.UUID(workspace_id))
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")

    workspace.reasoning_endpoint_url = payload.reasoning_endpoint_url
    workspace.reasoning_api_key_encrypted = encrypt_secret(payload.reasoning_api_key)
    workspace.reasoning_provider_label = payload.provider_label
    await db.commit()

    return {"workspace_id": workspace_id, "reasoning_provider_label": workspace.reasoning_provider_label, "configured": True}
