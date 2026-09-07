from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_workspace_from_session_or_key
from app.db.session import get_db
from app.models.pipeline_event import PipelineEvent
from app.models.telemetry import Span
from app.models.workspace import Workspace

router = APIRouter()

_STALE_AFTER = timedelta(minutes=15)  # same order as this app's own scan cadence


@router.get("/v1/pipeline-health")
async def pipeline_health(
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Ghost's own pipeline health, scoped to the caller's own workspace
    only -- not a platform-operator view of infrastructure across every
    tenant. Answers "is Ghost actually watching my data right now,"
    which is a different, narrower question than "is the whole
    deployment healthy."
    """
    last_data_received_at = (
        await db.execute(select(func.max(Span.started_at)).where(Span.workspace_id == workspace.id))
    ).scalar_one_or_none()

    last_scan_row = (
        await db.execute(
            select(PipelineEvent.occurred_at)
            .where(PipelineEvent.workspace_id == workspace.id, PipelineEvent.kind == "anomaly_scan", PipelineEvent.is_error.is_(False))
            .order_by(PipelineEvent.occurred_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    is_stale = last_data_received_at is None or (now - last_data_received_at) > _STALE_AFTER

    recent = (
        await db.execute(
            select(PipelineEvent)
            .where(PipelineEvent.workspace_id == workspace.id)
            .order_by(PipelineEvent.occurred_at.desc())
            .limit(15)
        )
    ).scalars().all()

    return {
        "last_data_received_at": last_data_received_at.isoformat() if last_data_received_at else None,
        "last_scan_at": last_scan_row.isoformat() if last_scan_row else None,
        "is_stale": is_stale,
        "recent_events": [
            {"kind": e.kind, "occurred_at": e.occurred_at.isoformat(), "is_error": e.is_error, "detail": e.detail}
            for e in recent
        ],
    }