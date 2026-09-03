"""
Promotes each service's fast "current" risk-score EWMA into its slow
"reference" baseline, on the same periodic cadence as edge latency
references (see app/graph/reference.py, which this deliberately
mirrors).

Excludes only services actually named in an open incident's own
evidence (primary_service, or a caller/callee on one of its edges) --
not every service that happens to share a name with something the
incident touches. Same reasoning as the edge version: a live incident's
elevated risk score should never get silently snapshotted in as that
service's new "normal."
"""
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.graph import ServiceNode
from app.models.incident import Incident

_MIN_SCANS_BEFORE_REFERENCE = 3  # needs a few scans before "current" is trustworthy as "normal"


def refresh_risk_reference_baselines(db, workspace_id) -> int:
    open_incidents = db.execute(
        select(Incident.primary_service, Incident.evidence).where(
            Incident.workspace_id == workspace_id,
            Incident.status.in_(["open", "diagnosing"]),
        )
    ).all()

    excluded_services: set[str] = set()
    for primary_service, evidence in open_incidents:
        excluded_services.add(primary_service)
        for item in evidence:
            for s in (item.get("caller"), item.get("callee")):
                if s:
                    excluded_services.add(s)

    nodes = db.execute(select(ServiceNode).where(ServiceNode.workspace_id == workspace_id)).scalars().all()

    updated = 0
    for node in nodes:
        if node.name in excluded_services:
            continue
        if node.risk_scan_count < _MIN_SCANS_BEFORE_REFERENCE:
            continue

        node.reference_risk_score = node.current_risk_score
        node.reference_risk_stddev = max(node.risk_score_variance ** 0.5, 1e-3)
        node.reference_risk_updated_at = datetime.now(timezone.utc)
        updated += 1

    db.commit()
    return updated