"""
SLO definition CRUD + the computed status endpoint the dashboard reads.

Status is always computed fresh from current rollup data (app/slo/status.py),
never stored -- same reasoning as reliability trends not storing its
own buckets. The burn-rate alert itself (app/slo/alerts.py) runs on
the hourly tick, not from here; this endpoint is read-only with
respect to alerting.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_workspace_from_session_or_key
from app.db.session import get_db
from app.models.slo import SLODefinition
from app.models.workspace import Workspace
from app.slo.status import compute_all_slo_statuses_async

router = APIRouter()


@router.get("/v1/slos")
async def list_slos(
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    definitions = (
        await db.execute(select(SLODefinition).where(SLODefinition.workspace_id == workspace.id))
    ).scalars().all()
    return [
        {
            "id": str(d.id),
            "service_name": d.service_name,
            "target_percent": d.target_percent,
            "window_days": d.window_days,
            "created_at": d.created_at.isoformat(),
            "alerting": d.alert_fired_at is not None,
        }
        for d in definitions
    ]


class CreateSLOIn(BaseModel):
    service_name: str
    target_percent: float = Field(gt=0, le=100)
    window_days: int = Field(default=30, ge=1, le=90)


@router.post("/v1/slos")
async def create_slo(
    payload: CreateSLOIn,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    One SLO per (workspace, service) -- re-posting for a service
    already defined updates it in place rather than erroring, since
    "change the target" is a normal thing to want and a 409 forcing a
    separate update flow would just be friction for no real benefit.
    """
    existing = (
        await db.execute(
            select(SLODefinition).where(
                SLODefinition.workspace_id == workspace.id,
                SLODefinition.service_name == payload.service_name,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.target_percent = payload.target_percent
        existing.window_days = payload.window_days
        existing.alert_fired_at = None  # a redefined target restarts the cooldown clean
        definition = existing
    else:
        definition = SLODefinition(
            workspace_id=workspace.id,
            service_name=payload.service_name,
            target_percent=payload.target_percent,
            window_days=payload.window_days,
        )
        db.add(definition)

    await db.commit()
    await db.refresh(definition)
    return {
        "id": str(definition.id),
        "service_name": definition.service_name,
        "target_percent": definition.target_percent,
        "window_days": definition.window_days,
    }


@router.delete("/v1/slos/{slo_id}")
async def delete_slo(
    slo_id: str,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    definition = (
        await db.execute(
            select(SLODefinition).where(SLODefinition.id == uuid.UUID(slo_id), SLODefinition.workspace_id == workspace.id)
        )
    ).scalar_one_or_none()
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SLO not found")

    await db.delete(definition)
    await db.commit()
    return {"id": slo_id, "deleted": True}


@router.get("/v1/slos/status")
async def slo_status(
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    statuses = await compute_all_slo_statuses_async(db, workspace.id)
    return [s.to_dict() for s in statuses]