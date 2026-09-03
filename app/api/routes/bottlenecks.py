from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends

from app.api.deps import get_workspace_from_session_or_key
from app.bottleneck.engine import compute_bottlenecks
from app.db.session import get_db
from app.models.graph import ServiceEdge, ServiceNode
from app.models.workspace import Workspace

router = APIRouter()


@router.get("/v1/bottlenecks")
async def list_bottlenecks(
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Computed on-demand rather than read from a cached table -- a single
    workspace's graph is small enough (dozens to low hundreds of edges)
    for this to be cheap, and it guarantees the dashboard never shows a
    stale risk score between background scan runs.

    `risk_score` itself is always this fresh on-demand value. The
    reference/deviation fields come from ServiceNode's own risk-score
    baseline (see app/bottleneck/baseline.py), updated on the slower
    5-minute scan cadence -- so "is this unusually risky FOR THIS
    SERVICE" is judged against that service's own learned normal,
    not a single fixed cutoff applied uniformly to every service
    regardless of its typical fan-in or criticality.
    """
    edges = (await db.execute(select(ServiceEdge).where(ServiceEdge.workspace_id == workspace.id))).scalars().all()
    risks = compute_bottlenecks(edges)

    nodes = (await db.execute(select(ServiceNode).where(ServiceNode.workspace_id == workspace.id))).scalars().all()
    nodes_by_name = {n.name: n for n in nodes}

    result = []
    for r in risks:
        node = nodes_by_name.get(r.service)
        has_reference = node is not None and node.reference_risk_updated_at is not None
        zscore = None
        if has_reference and node.reference_risk_stddev >= 1e-6:
            zscore = round((r.risk_score - node.reference_risk_score) / node.reference_risk_stddev, 2)

        result.append({
            "service": r.service, "fan_in": r.fan_in, "fan_out": r.fan_out,
            "critical_path_membership": r.critical_path_membership,
            "error_rate_baseline": r.error_rate_baseline, "risk_score": r.risk_score,
            "contributing_edges": r.contributing_edges,
            "reference_risk_score": node.reference_risk_score if has_reference else None,
            "has_reference_baseline": has_reference,
            "risk_zscore": zscore,
        })
    return result


@router.get("/v1/graph")
async def get_behavioral_graph(
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
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