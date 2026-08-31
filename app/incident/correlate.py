"""
Groups anomalies detected in one scan pass into incidents. Two anomalies
are considered part of the same incident if they touch a shared service
(the graph-connectivity signal from the original design doc: cache miss
-> DB load -> API latency should surface as ONE incident, not three
separate alerts).

Also folds new anomalies into an already-open incident on the same
service, as long as that incident has been touched within the recency
window -- matched against `last_seen_at` (updated every time a fresh
anomaly correlates into it), NOT `started_at`. An incident that keeps
getting anomalies should keep absorbing them indefinitely, no matter
how long it's been open; matching on creation time instead would mean
any incident older than the window silently stops absorbing new
anomalies for the same ongoing problem and starts spawning a fresh
duplicate incident once per window -- which is worse than the original
"one incident, retried forever" problem for anything that takes longer
than the window to resolve, which describes most real incidents.
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


def _merge_evidence(existing_evidence: list[dict], new_group: list[Anomaly]) -> list[dict]:
    """
    Merges freshly-detected anomalies into an incident's evidence,
    deduplicating by (edge, metric) rather than appending unconditionally.
    Without this, an anomaly that's still ongoing when the next scan runs
    (the common case -- most incidents last more than one 30s scan cycle)
    would re-append an identical entry every cycle, growing the evidence
    list without bound for as long as the incident stays open.
    """
    merged: dict[tuple[str, str], dict] = {(e["edge"], e["metric"]): e for e in existing_evidence}
    for a in new_group:
        merged[(a.edge, a.metric)] = a.to_evidence_dict()  # latest reading replaces the prior one
    return list(merged.values())


def correlate_and_persist(db: Session, workspace_id, anomalies: list[Anomaly]) -> list[tuple[Incident, bool]]:
    """
    Returns (incident, should_dispatch_reasoning) pairs. should_dispatch
    is True only for a newly-opened incident or one that just escalated
    in severity -- NOT for every routine re-correlation of an anomaly
    that's simply still ongoing. Without this distinction, an incident
    that stays open for N scan cycles would trigger N external reasoning
    calls, one per cycle, for as long as it remains open -- a real cost
    and noise problem for any configured reasoning service, not just a
    cosmetic one.
    """
    if not anomalies:
        return []

    groups = _group_connected(anomalies)
    cutoff = datetime.now(timezone.utc) - _RECENT_INCIDENT_WINDOW
    results: list[tuple[Incident, bool]] = []

    for group in groups:
        primary = max(group, key=lambda a: abs(a.zscore))
        services_in_group = {a.caller for a in group} | {a.callee for a in group}

        existing = db.execute(
            select(Incident).where(
                Incident.workspace_id == workspace_id,
                Incident.status.in_(["open", "diagnosing"]),
                Incident.last_seen_at >= cutoff,
                Incident.primary_service.in_(services_in_group),
            )
        ).scalars().first()

        if existing:
            existing.evidence = _merge_evidence(existing.evidence, group)
            existing.last_seen_at = datetime.now(timezone.utc)
            new_severity = _severity_for(group)
            severity_rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            escalated = severity_rank[new_severity] > severity_rank[existing.severity]
            if escalated:
                existing.severity = new_severity
            db.add(Event(
                incident_id=existing.id,
                kind="anomaly_correlated",
                message=f"Additional anomaly correlated: {primary.edge} ({primary.metric} z={primary.zscore:.1f})",
            ))
            results.append((existing, escalated))
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
            results.append((incident, True))

    db.commit()
    return results