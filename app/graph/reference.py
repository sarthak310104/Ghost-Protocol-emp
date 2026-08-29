"""
Promotes each edge's fast "current" EWMA into the slow "reference"
baseline on a periodic cadence (see beat schedule / ops runbook -- not
wired into celery beat by default since the right cadence is workload-
dependent; expose as an admin-triggerable task and a suggested cron).

Deliberately skips edges that are part of a currently-open incident, so
a live incident's abnormal numbers never get snapshotted in as the new
"normal" -- otherwise the system would learn to treat the outage as
expected behavior.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.graph import ServiceEdge
from app.models.incident import Incident


def refresh_reference_baselines(db: Session, workspace_id) -> int:
    open_incident_services = set(
        db.execute(
            select(Incident.primary_service).where(
                Incident.workspace_id == workspace_id,
                Incident.status.in_(["open", "diagnosing"]),
            )
        ).scalars().all()
    )

    edges = db.execute(select(ServiceEdge).where(ServiceEdge.workspace_id == workspace_id)).scalars().all()

    updated = 0
    for edge in edges:
        if edge.callee in open_incident_services or edge.caller in open_incident_services:
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
