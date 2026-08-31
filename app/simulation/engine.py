"""
Statistical what-if engine (the honest v1 scope, not the sandboxed
system replica from the original design doc -- that's a multi-month
project on its own and is explicitly deferred).

What this actually estimates, and what it does NOT: it does not simulate
a specific proposed config value (e.g. "Redis TTL 30s -> 300s") against
a replica, because we have no causal model connecting a config value to
a metric. What it DOES do, grounded entirely in data we already collect:

1. Mean-reversion projection: for each anomalous metric, project where
   it would land if the system returned to its own historical "normal"
   (the reference baseline each edge already maintains), with a
   confidence interval derived from that baseline's own observed spread.
2. Blast radius: every other edge touching the same services, with its
   own current-vs-reference deviation, so the report shows what else is
   plausibly affected -- not just the one edge that triggered the
   incident.

Every number in the output is either "what we've already measured" or
"where it would sit if it returned to its own history" -- there's no
hidden model pretending to know what a specific fix will do.
"""
import math
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.graph import ServiceEdge

_Z_95 = 1.96  # two-sided 95% CI multiplier -- matches the confidence level Ghost Protocol reports everywhere else


@dataclass
class MetricProjection:
    edge: str
    metric: str
    current: float
    reference: float
    ci_low: float
    ci_high: float
    note: str


def _project_edge_reversion(edge: ServiceEdge) -> MetricProjection | None:
    if edge.reference_updated_at is None:
        return None
    stddev = edge.reference_latency_stddev or 0.0
    return MetricProjection(
        edge=f"{edge.caller}->{edge.callee}",
        metric="latency_p99_ms",
        current=round(edge.current_latency_ms_p99, 2),
        reference=round(edge.reference_latency_ms, 2),
        ci_low=round(max(edge.reference_latency_ms - _Z_95 * stddev, 0), 2),
        ci_high=round(edge.reference_latency_ms + _Z_95 * stddev, 2),
        note="Projected value if this edge reverts to its own historical baseline.",
    )


def simulate_incident_resolution(db: Session, workspace_id: uuid.UUID, primary_service: str,
                                  affected_edges: set[tuple[str, str]]) -> dict:
    """
    `affected_edges` is the set of exact (caller, callee) pairs actually
    named in the incident's evidence -- NOT the broader set of service
    names those edges touch. Matching on service names instead of exact
    edges was a real bug: any edge sharing just the primary_service name
    (e.g. an unrelated healthy caller->redis edge, when redis is the
    primary_service) got misclassified as "directly affected" by the
    incident rather than correctly reported as blast radius, or excluded
    entirely if it wasn't even a genuine part of the problem.
    """
    all_edges = db.execute(
        select(ServiceEdge).where(ServiceEdge.workspace_id == workspace_id)
    ).scalars().all()

    directly_affected = [e for e in all_edges if (e.caller, e.callee) in affected_edges]
    blast_radius_edges = [e for e in all_edges if e not in directly_affected and (
        e.caller == primary_service or e.callee == primary_service
    )]

    projections = [p for p in (_project_edge_reversion(e) for e in directly_affected) if p is not None]
    blast_radius = [p for p in (_project_edge_reversion(e) for e in blast_radius_edges) if p is not None]

    def improvement_summary(p: MetricProjection) -> dict | None:
        """
        Point estimate plus a 95% CI on the improvement itself, not just
        on the projected value -- the CI is inverted relative to the
        value's own CI, since a *smaller* projected latency (ci_low on
        the value) is the *larger* improvement, and vice versa.
        """
        if p.current <= 0:
            return None
        pct = lambda projected: round(100 * (p.current - projected) / p.current, 1)  # noqa: E731
        return {
            "point_estimate_pct": pct(p.reference),
            "ci_95_low_pct": pct(p.ci_high),   # worst case: latency only reverts to the CI's upper bound
            "ci_95_high_pct": pct(p.ci_low),   # best case: latency reverts to the CI's lower bound
        }

    return {
        "primary_service": primary_service,
        "method": "statistical_mean_reversion",  # not a sandboxed replica -- see module docstring
        "confidence_level": 0.95,
        "projections": [
            {**p.__dict__, "projected_improvement": improvement_summary(p)} for p in projections
        ],
        "blast_radius": [p.__dict__ for p in blast_radius],
    }