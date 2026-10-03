"""
Historical reliability trends: per-service incident frequency and MTTR
over time, distinct from the live/current-state dashboard (Services,
Bottlenecks) which only ever shows "right now."

Deliberately does NOT compute an uptime percentage. Raw Span/MetricPoint
rows are pruned after `settings.ghost_telemetry_retention_hours`
(app/ingestion/retention.py) -- there is no continuous health signal to
look back at beyond that window. Incident rows are never pruned, so
they're the only thing honestly usable for a long-horizon view, but an
incident captures "a problem was detected," not a precise down/up
interval -- deriving an uptime percentage from that would overclaim
precision the data doesn't have. Same restraint the simulation engine
and config-drift detection apply elsewhere in this codebase: surface
exactly what the data supports, not an inferred number dressed up as
measured.

Buckets are rolling 7-day windows counted back from "now" (weeks_ago=0
is the current 0-6-day-old window), not calendar weeks -- there's no
reason to care about ISO week boundaries here, only about recency.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.incident import Incident

# Same bounding rationale as _MAX_DEPLOYMENTS_SCANNED_PER_SERVICE in
# app/deployments/drift.py -- caps the scan for a workspace with an
# enormous incident history rather than leaving it unbounded.
_MAX_INCIDENTS_SCANNED = 5000


@dataclass
class WeeklyBucket:
    weeks_ago: int  # 0 = most recent 7-day window
    bucket_start: datetime
    bucket_end: datetime
    incident_count: int = 0
    severity_counts: dict[str, int] = field(default_factory=dict)
    resolved_count: int = 0  # how many of incident_count have an MTTR data point
    mttr_mean_seconds: float | None = None
    mttr_median_seconds: float | None = None

    def to_dict(self) -> dict:
        return {
            "weeks_ago": self.weeks_ago,
            "bucket_start": self.bucket_start.isoformat(),
            "bucket_end": self.bucket_end.isoformat(),
            "incident_count": self.incident_count,
            "severity_counts": self.severity_counts,
            "resolved_count": self.resolved_count,
            "mttr_mean_seconds": self.mttr_mean_seconds,
            "mttr_median_seconds": self.mttr_median_seconds,
        }


@dataclass
class ServiceReliabilityTrend:
    service_name: str
    # Oldest first -- weeks_ago descending -- so a chart can map the
    # list left-to-right as time moving forward, with no reversal needed.
    weeks: list[WeeklyBucket]

    def to_dict(self) -> dict:
        return {"service_name": self.service_name, "weeks": [w.to_dict() for w in self.weeks]}


def _bucket_incidents(
    incidents: list[Incident], weeks: int, now: datetime,
) -> dict[str, list[WeeklyBucket]]:
    """
    Pure, DB-free -- `incidents` can be any list already scoped to one
    workspace and the desired lookback window; this only buckets and
    aggregates. An incident older than `weeks` 7-day windows from `now`
    is silently excluded (the caller's query is expected to have
    already bounded this, but it's harmless here either way).
    """
    by_service: dict[str, list[WeeklyBucket]] = {}
    mttrs_by_service_bucket: dict[tuple[str, int], list[float]] = {}

    def _buckets_for(service_name: str) -> list[WeeklyBucket]:
        if service_name not in by_service:
            fresh = []
            for weeks_ago in range(weeks):
                bucket_end = now - timedelta(days=7 * weeks_ago)
                bucket_start = bucket_end - timedelta(days=7)
                fresh.append(WeeklyBucket(weeks_ago=weeks_ago, bucket_start=bucket_start, bucket_end=bucket_end))
            by_service[service_name] = fresh
        return by_service[service_name]

    for incident in incidents:
        age_days = (now - incident.started_at).total_seconds() / 86400
        weeks_ago = int(age_days // 7)
        if weeks_ago < 0 or weeks_ago >= weeks:
            continue  # future-dated (clock skew) or outside the lookback window

        buckets = _buckets_for(incident.primary_service)
        bucket = buckets[weeks_ago]
        bucket.incident_count += 1
        bucket.severity_counts[incident.severity] = bucket.severity_counts.get(incident.severity, 0) + 1

        if incident.resolved_at is not None:
            mttr_seconds = (incident.resolved_at - incident.started_at).total_seconds()
            mttrs_by_service_bucket.setdefault((incident.primary_service, weeks_ago), []).append(mttr_seconds)

    for (service_name, weeks_ago), mttrs in mttrs_by_service_bucket.items():
        bucket = by_service[service_name][weeks_ago]
        bucket.resolved_count = len(mttrs)
        bucket.mttr_mean_seconds = sum(mttrs) / len(mttrs)
        bucket.mttr_median_seconds = median(mttrs)

    # Return oldest-first per service.
    return {service: list(reversed(buckets)) for service, buckets in by_service.items()}


def _to_results(bucketed: dict[str, list[WeeklyBucket]]) -> list[ServiceReliabilityTrend]:
    return [
        ServiceReliabilityTrend(service_name=name, weeks=weeks)
        for name, weeks in sorted(bucketed.items())
    ]


def _scan_query(workspace_id: uuid.UUID, weeks: int, now: datetime):
    cutoff = now - timedelta(days=7 * weeks)
    return (
        select(Incident)
        .where(Incident.workspace_id == workspace_id, Incident.started_at >= cutoff)
        .order_by(Incident.started_at.desc())
        .limit(_MAX_INCIDENTS_SCANNED)
    )


def compute_reliability_trends(db: Session, workspace_id: uuid.UUID, weeks: int = 12) -> list[ServiceReliabilityTrend]:
    """Sync entry point -- not currently called from a Celery task, but kept consistent with the rest of this codebase's sync/async pairing."""
    now = datetime.now(timezone.utc)
    rows = db.execute(_scan_query(workspace_id, weeks, now)).scalars().all()
    return _to_results(_bucket_incidents(list(rows), weeks, now))


async def compute_reliability_trends_async(
    db, workspace_id: uuid.UUID, weeks: int = 12,
) -> list[ServiceReliabilityTrend]:
    """Async entry point -- used from the FastAPI route."""
    now = datetime.now(timezone.utc)
    result = await db.execute(_scan_query(workspace_id, weeks, now))
    return _to_results(_bucket_incidents(list(result.scalars().all()), weeks, now))