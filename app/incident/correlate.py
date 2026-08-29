"""
Groups anomalies detected in one scan pass into incidents. Two anomalies
are considered part of the same incident if they touch a shared service
(the graph-connectivity signal from the original design doc: cache miss
-> DB load -> API latency should surface as ONE incident, not three
separate alerts).

Also folds new anomalies into an already-open incident on the same
service within a recency window, instead of opening a duplicate.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.incident.detect import Anomaly
from app.models.incident import Event, Incident

_RECENT_INCIDENT_WINDOW = timedelta(minutes=20)


def _group_connected(anomalies: list[Anomaly]) -> list[list[Anomaly]]:
    """Union-find style grouping by shared service name."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a in anomalies:
        union(a.caller, a.callee)

    groups: dict[str, list[Anomaly]] = {}
    for a in anomalies:
        root = find(a.caller)
        groups.setdefault(root, []).append(a)
    return list(groups.values())


def _severity_for(anomalies: list[Anomaly]) -> str:
    worst = max(abs(a.zscore) for a in anomalies)
    if worst >= 8:
        return "critical"
    if worst >= 5:
        return "high"
    if worst >= 3:
        return "medium"
    return "low"


def correlate_and_persist(db: Session, workspace_id, anomalies: list[Anomaly]) -> list[Incident]:
    if not anomalies:
        return []

    groups = _group_connected(anomalies)
    cutoff = datetime.now(timezone.utc) - _RECENT_INCIDENT_WINDOW
    touched_incidents: list[Incident] = []

    for group in groups:
        primary = max(group, key=lambda a: abs(a.zscore))
        services_in_group = {a.caller for a in group} | {a.callee for a in group}

        existing = db.execute(
            select(Incident).where(
                Incident.workspace_id == workspace_id,
                Incident.status.in_(["open", "diagnosing"]),
                Incident.started_at >= cutoff,
                Incident.primary_service.in_(services_in_group),
            )
        ).scalars().first()

        if existing:
            existing.evidence = [*existing.evidence, *[a.to_evidence_dict() for a in group]]
            # Recompute severity from just the newly-correlated anomalies; if
            # they're worse than what's already recorded, this escalates the
            # incident rather than only ever holding its original severity.
            new_severity = _severity_for(group)
            severity_rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            if severity_rank[new_severity] > severity_rank[existing.severity]:
                existing.severity = new_severity
            db.add(Event(
                incident_id=existing.id,
                kind="anomaly_correlated",
                message=f"Additional anomaly correlated: {primary.edge} ({primary.metric} z={primary.zscore:.1f})",
            ))
            touched_incidents.append(existing)
        else:
            incident = Incident(
                workspace_id=workspace_id,
                title=f"Elevated {primary.metric.replace('_', ' ')} on {primary.edge}",
                primary_service=primary.callee,
                severity=_severity_for(group),
                evidence=[a.to_evidence_dict() for a in group],
            )
            db.add(incident)
            db.flush()
            db.add(Event(
                incident_id=incident.id,
                kind="incident_opened",
                message=f"Incident opened from {len(group)} correlated anomaly(ies), worst z={abs(primary.zscore):.1f}",
            ))
            touched_incidents.append(incident)

    db.commit()
    return touched_incidents
