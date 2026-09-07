"""
The one genuinely public, unauthenticated endpoint in this API --
everything else requires a session or bearer key. Deliberately hardcoded
to GHOST_DEMO_WORKSPACE_ID and nothing else: there's no workspace_id
parameter anywhere in this file, on purpose, so this can never become a
way to read arbitrary workspace data. A visitor should be able to see
that Ghost is a real, live system before they ever log in -- this is
what the landing page calls to make that true.

Being public and unauthenticated means CORS doesn't protect it -- CORS
only restricts browser-originated cross-origin calls, not a script or
curl hitting it directly. Since every call does real DB reads against a
free-tier Postgres with a monthly compute-hour cap, this gets the same
per-IP rate limit as login, for the same underlying reason: not a
defense against a determined attacker, just cheap insurance against
this being hammered into burning through the database's free quota.
"""
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.bottleneck.engine import compute_bottlenecks
from app.core.config import get_settings
from app.core.redis_client import get_redis
from app.db.sync_session import SyncSessionLocal
from app.models.graph import ServiceEdge
from app.models.incident import Incident

router = APIRouter()


async def _check_preview_rate_limit(request: Request) -> None:
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    key = f"demo_preview:{client_ip}"
    r = get_redis()
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, 60)
    if count > settings.ghost_login_rate_limit_per_minute:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests -- try again shortly")


@router.get("/v1/public/demo-preview")
async def demo_preview(request: Request):
    await _check_preview_rate_limit(request)

    settings = get_settings()
    if not settings.ghost_demo_workspace_id:
        return {"configured": False}

    workspace_id = uuid.UUID(settings.ghost_demo_workspace_id)

    with SyncSessionLocal() as db:
        edges = db.execute(select(ServiceEdge).where(ServiceEdge.workspace_id == workspace_id)).scalars().all()
        services_observed = len({s for e in edges for s in (e.caller, e.callee)})

        open_incidents = db.execute(
            select(Incident)
            .where(Incident.workspace_id == workspace_id, Incident.status.in_(["open", "diagnosing"]))
            .order_by(Incident.started_at.desc())
            .limit(3)
        ).scalars().all()

        top_bottleneck = None
        risks = compute_bottlenecks(edges)
        if risks:
            top = max(risks, key=lambda r: r.risk_score)
            top_bottleneck = {"service": top.service, "risk_score": top.risk_score}

    return {
        "configured": True,
        "services_observed": services_observed,
        "open_incident_count": len(open_incidents),
        "recent_incidents": [
            {"title": i.title, "severity": i.severity, "primary_service": i.primary_service}
            for i in open_incidents
        ],
        "top_bottleneck": top_bottleneck,
    }