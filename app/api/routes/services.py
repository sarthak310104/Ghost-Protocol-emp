from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_workspace_from_session_or_key
from app.db.session import get_db
from app.models.graph import ServiceEdge, ServiceNode
from app.models.workspace import Workspace

router = APIRouter()


@router.get("/v1/services")
async def list_services(
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Unlike /v1/bottlenecks (which only lists services that appear in
    *current* edges), this starts from ServiceNode directly -- a
    service that stopped receiving traffic still shows up here, with
    its last_seen_at telling you it's gone quiet, rather than silently
    vanishing from the dashboard the moment its edges age out.
    """
    nodes = (await db.execute(select(ServiceNode).where(ServiceNode.workspace_id == workspace.id))).scalars().all()
    edges = (await db.execute(select(ServiceEdge).where(ServiceEdge.workspace_id == workspace.id))).scalars().all()

    fan_in: dict[str, int] = defaultdict(int)
    fan_out: dict[str, int] = defaultdict(int)
    for e in edges:
        fan_out[e.caller] += 1
        fan_in[e.callee] += 1

    result = []
    for n in nodes:
        has_reference = n.reference_risk_updated_at is not None
        zscore = None
        if has_reference and n.reference_risk_stddev >= 1e-6:
            zscore = round((n.current_risk_score - n.reference_risk_score) / n.reference_risk_stddev, 2)

        result.append({
            "name": n.name,
            "first_seen_at": n.first_seen_at.isoformat(),
            "last_seen_at": n.last_seen_at.isoformat(),
            "fan_in": fan_in.get(n.name, 0),
            "fan_out": fan_out.get(n.name, 0),
            "current_risk_score": round(n.current_risk_score, 3),
            "has_reference_baseline": has_reference,
            "risk_zscore": zscore,
        })

    result.sort(key=lambda s: s["last_seen_at"], reverse=True)
    return result