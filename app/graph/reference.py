"""
Promotes each edge's fast "current" EWMA into the slow "reference"
baseline on a periodic cadence (see beat schedule / ops runbook -- not
wired into celery beat by default since the right cadence is workload-
dependent; expose as an admin-triggerable task and a suggested cron).

Deliberately skips only the SPECIFIC edges named in an open incident's
own evidence, so a live incident's abnormal numbers never get
snapshotted in as the new "normal" for those particular edges.

This is intentionally narrower than "skip every edge touching the
incident's primary_service" -- that broader exclusion was a real bug:
a busy/central service (e.g. redis, called by many unrelated things)
would have EVERY edge touching it blocked from ever establishing a
reference baseline for as long as any incident involving that service
stayed open, even edges with no relationship to the incident at all.
That silently blinded anomaly detection on those other edges (not just
blast-radius reporting) for as long as the unrelated incident lasted --
which, for a genuinely central service, could be indefinitely.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.graph import ServiceEdge
from app.models.incident import Incident


def refresh_reference_baselines(db: Session, workspace_id) -> int:
    open_incidents = db.execute(
        select(Incident.evidence).where(
            Incident.workspace_id == workspace_id,
            Incident.status.in_(["open", "diagnosing"]),
        )
    ).scalars().all()

    excluded_edges: set[tuple[str, str]] = set()
    for evidence in open_incidents:
        for item in evidence:
            caller, callee = item.get("caller"), item.get("callee")
            if caller and callee:
                excluded_edges.add((caller, callee))

    edges = db.execute(select(ServiceEdge).where(ServiceEdge.workspace_id == workspace_id)).scalars().all()

    updated = 0
    for edge in edges:
        if (edge.caller, edge.callee) in excluded_edges:
            continue
        if edge.sample_count < 5:
            continue  # not enough data yet to trust as "normal"

        edge.reference_latency_ms = edge.current_latency_ms_p99
        edge.reference_latency_stddev = max(edge.current_latency_variance ** 0.5, 1e-3)
        edge.reference_error_rate = edge.current_error_rate
        from datetime import datetime, timezone
        edge.reference_updated_at = datetime.now(timezone.utc)
        updated += 1

    db.commit()
    return updated