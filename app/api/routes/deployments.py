from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_workspace_from_api_key, get_workspace_from_session_or_key
from app.db.session import get_db
from app.deployments.drift import compute_config_drift_async
from app.deployments.retrospective import run_retrospective_comparison_async
from app.models.deployment import Deployment
from app.models.workspace import Workspace

router = APIRouter()


class RecordDeploymentIn(BaseModel):
    service_name: str
    version: str
    notes: str | None = None
    deployed_at: datetime | None = None  # defaults to now if omitted
    # Optional, flat {key: value} snapshot of this service's tracked
    # config AT this deploy -- the full current state, not a diff
    # against the previous deploy. Omit entirely for a deploy with
    # nothing to report; config drift detection (app/deployments/drift.py)
    # treats "no snapshot submitted" differently from "submitted an
    # empty snapshot" -- the former is skipped when looking for a
    # key's history, the latter means every previously-tracked key was
    # explicitly unset as of this deploy.
    config_snapshot: dict[str, str] | None = None


@router.post("/v1/deployments")
async def record_deployment(
    payload: RecordDeploymentIn,
    workspace: Workspace = Depends(get_workspace_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    """
    A CI/CD pipeline step calls this right after a deploy completes. This
    is deliberately explicit rather than inferred from telemetry --
    reliably detecting "a deployment happened" from span/metric data
    alone isn't something Ghost Protocol attempts. Bearer-key only --
    this is a machine-to-machine write, same as ingestion, not something
    a browser session should be doing.
    """
    deployment = Deployment(
        workspace_id=workspace.id,
        service_name=payload.service_name,
        version=payload.version,
        notes=payload.notes,
        deployed_at=payload.deployed_at or datetime.now(timezone.utc),
        config_snapshot=payload.config_snapshot,
    )
    db.add(deployment)
    await db.commit()
    await db.refresh(deployment)
    return {"id": str(deployment.id), "service_name": deployment.service_name, "version": deployment.version,
            "deployed_at": deployment.deployed_at.isoformat()}


@router.get("/v1/deployments")
async def list_deployments(
    limit: int = 100,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Newest first, capped at `limit` -- a long-lived workspace could
    accumulate a large deployment history, and the dashboard only ever
    needs a recent window of it, not the full archive in one response.
    """
    deployments = (
        await db.execute(
            select(Deployment)
            .where(Deployment.workspace_id == workspace.id)
            .order_by(Deployment.deployed_at.desc())
            .limit(min(limit, 500))
        )
    ).scalars().all()
    return [
        {
            "id": str(d.id), "service_name": d.service_name, "version": d.version,
            "deployed_at": d.deployed_at.isoformat(), "notes": d.notes,
        }
        for d in deployments
    ]


@router.get("/v1/deployments/{service_name}/config-drift")
async def get_config_drift(
    service_name: str,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Config drift for one service as of right now -- the same
    computation an incident's evidence package includes (see
    app/deployments/drift.py and GET /v1/incidents/{id}/evidence), but
    queryable standalone rather than only in the context of an open
    incident. Useful for a "what's currently drifted on this service"
    view on its own, e.g. before something has actually gone wrong.
    """
    drift = await compute_config_drift_async(db, workspace.id, {service_name}, datetime.now(timezone.utc))
    return [d.to_dict() for d in drift]


@router.get("/v1/deployments/retrospective-comparison")
async def retrospective_comparison(
    caller: str,
    callee: str,
    changed_at: datetime,
    window_minutes: int = 60,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Real metrics on one edge in a window before `changed_at` vs a
    window after -- intended to be called with a config-drift event's
    own `changed_at` (see GET /v1/deployments/{service}/config-drift),
    to ask "did the numbers on this edge actually move around that
    change." `caller`/`callee` are supplied separately because drift
    is tracked per-service, not per-edge -- a service can be the
    caller on several edges, and this needs one specific edge to
    compare. Weaker evidence than cohort comparison (GET
    /v1/cohort-analysis): before/after is confounded by anything else
    that changed in the same window, where a concurrent cohort isn't --
    see app/deployments/retrospective.py's docstring.
    """
    result = await run_retrospective_comparison_async(db, workspace.id, caller, callee, changed_at, window_minutes)
    return result.to_dict()