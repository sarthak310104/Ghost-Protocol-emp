from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends

from app.api.deps import get_workspace_from_api_key
from app.bottleneck.engine import compute_bottlenecks
from app.db.session import get_db
from app.models.graph import ServiceEdge
from app.models.workspace import Workspace

router = APIRouter()


@router.get("/v1/bottlenecks")
async def list_bottlenecks(
    workspace: Workspace = Depends(get_workspace_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Computed on-demand rather than read from a cached table -- a single
    workspace's graph is small enough (dozens to low hundreds of edges)
    for this to be cheap, and it guarantees the dashboard never shows a
    stale risk score between background scan runs.
    """
    edges = (await db.execute(select(ServiceEdge).where(ServiceEdge.workspace_id == workspace.id))).scalars().all()
    risks = compute_bottlenecks(edges)
    return [
        {
            "service": r.service, "fan_in": r.fan_in, "fan_out": r.fan_out,
            "critical_path_membership": r.critical_path_membership,
            "error_rate_baseline": r.error_rate_baseline, "risk_score": r.risk_score,
            "contributing_edges": r.contributing_edges,
        }
        for r in risks
    ]


@router.get("/v1/graph")
async def get_behavioral_graph(
    workspace: Workspace = Depends(get_workspace_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Raw graph + current/reference baselines per edge, for the dashboard's graph view."""
    edges = (await db.execute(select(ServiceEdge).where(ServiceEdge.workspace_id == workspace.id))).scalars().all()
    return [
        {
            "caller": e.caller, "callee": e.callee,
            "current_latency_ms_p50": round(e.current_latency_ms_p50, 2),
            "current_latency_ms_p99": round(e.current_latency_ms_p99, 2),
            "current_error_rate": round(e.current_error_rate, 4),
            "reference_latency_ms": round(e.reference_latency_ms, 2),
            "reference_error_rate": round(e.reference_error_rate, 4),
            "has_reference_baseline": e.reference_updated_at is not None,
            "sample_count": e.sample_count,
        }
        for e in edges
    ]
