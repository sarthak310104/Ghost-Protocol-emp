from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_workspace_from_session_or_key
from app.core.crypto import encrypt_secret
from app.core.security import generate_api_key, hash_api_key
from app.db.session import get_db
from app.models.workspace import ApiKey, Workspace
from app.notifications.webhook import is_sendable_webhook_url

router = APIRouter()


@router.get("/v1/workspace")
async def get_workspace_settings(
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Never returns a raw key or key_hash -- a workspace's own API keys
    are only ever shown as metadata here (label, when created, when
    last used, active or revoked). The raw value is only ever visible
    once, at creation time, same rule as the admin-created key.
    """
    keys = (
        await db.execute(select(ApiKey).where(ApiKey.workspace_id == workspace.id).order_by(ApiKey.created_at.desc()))
    ).scalars().all()

    return {
        "name": workspace.name,
        "created_at": workspace.created_at.isoformat(),
        "api_keys": [
            {
                "id": str(k.id), "label": k.label, "is_active": k.is_active,
                "created_at": k.created_at.isoformat(),
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            }
            for k in keys
        ],
    }


class CreateApiKeyIn(BaseModel):
    label: str = "default"


@router.post("/v1/workspace/api-keys")
async def create_api_key(
    payload: CreateApiKeyIn,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Self-service key creation -- previously the only way to get a new
    key was the admin-secret-gated workspace-creation endpoint, which
    only makes sense for the platform operator, not a workspace that
    just wants to rotate or add a key for itself.
    """
    raw_key = generate_api_key()
    key = ApiKey(workspace_id=workspace.id, key_hash=hash_api_key(raw_key), label=payload.label.strip() or "default")
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return {
        "id": str(key.id), "label": key.label, "created_at": key.created_at.isoformat(),
        "api_key": raw_key,  # shown exactly once -- never retrievable again after this response
    }


@router.post("/v1/workspace/api-keys/{key_id}/revoke")
async def revoke_api_key(
    key_id: str,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    key = (
        await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.workspace_id == workspace.id))
    ).scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")

    key.is_active = False
    await db.commit()
    return {"id": str(key.id), "is_active": False}


@router.get("/v1/workspace/reasoning")
async def get_reasoning_config(
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
):
    """
    Never returns the stored API key, encrypted or otherwise -- same
    "shown once at write time" rule as everything else in this file.
    A workspace can see THAT it's configured and what it's pointed at,
    not the credential itself.
    """
    return {
        "reasoning_endpoint_url": workspace.reasoning_endpoint_url,
        "reasoning_provider_label": workspace.reasoning_provider_label,
        "configured": workspace.reasoning_endpoint_url is not None,
    }


class ConfigureReasoningIn(BaseModel):
    reasoning_endpoint_url: str
    reasoning_api_key: str
    provider_label: str = "custom"


@router.put("/v1/workspace/reasoning")
async def configure_own_reasoning(
    payload: ConfigureReasoningIn,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Session-gated equivalent of PUT /v1/admin/workspaces/{id}/reasoning
    -- that endpoint still exists for the platform operator (bulk
    provisioning, no session needed), but there was previously no way
    for a workspace to configure its own reasoning connection from its
    own dashboard without the platform operator's shared admin secret.
    Scoped to the caller's own workspace only -- no workspace_id
    parameter, deliberately, same reasoning as the API-key endpoints
    above.
    """
    workspace.reasoning_endpoint_url = payload.reasoning_endpoint_url
    workspace.reasoning_api_key_encrypted = encrypt_secret(payload.reasoning_api_key)
    workspace.reasoning_provider_label = payload.provider_label
    await db.commit()

    return {
        "reasoning_endpoint_url": workspace.reasoning_endpoint_url,
        "reasoning_provider_label": workspace.reasoning_provider_label,
        "configured": True,
    }


@router.delete("/v1/workspace/reasoning")
async def disconnect_reasoning(
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    workspace.reasoning_endpoint_url = None
    workspace.reasoning_api_key_encrypted = None
    workspace.reasoning_provider_label = "unconfigured"
    await db.commit()
    return {"configured": False}


@router.get("/v1/workspace/notifications")
async def get_notification_config(
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
):
    """See app/notifications/webhook.py -- one URL, POSTed on incident open and resolve."""
    return {
        "notification_webhook_url": workspace.notification_webhook_url,
        "configured": workspace.notification_webhook_url is not None,
    }


class ConfigureNotificationsIn(BaseModel):
    notification_webhook_url: str


@router.put("/v1/workspace/notifications")
async def configure_notifications(
    payload: ConfigureNotificationsIn,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    url = payload.notification_webhook_url.strip()
    if not is_sendable_webhook_url(url):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Webhook URL must start with http:// or https://")

    workspace.notification_webhook_url = url
    await db.commit()
    return {"notification_webhook_url": workspace.notification_webhook_url, "configured": True}


@router.delete("/v1/workspace/notifications")
async def disconnect_notifications(
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    workspace.notification_webhook_url = None
    await db.commit()
    return {"configured": False}