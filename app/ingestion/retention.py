"""
Raw telemetry retention. Nothing else in this codebase deletes spans or
metric points -- without this, a workspace that ingests continuously
(the demo workspace in particular, via app/workers/demo_seeder.py)
grows its storage forever. Neon's free Postgres tier caps at 0.5GB,
so this is what keeps a free, long-running demo deployment from
eventually filling its own database and failing writes.

Deletes raw Span/MetricPoint rows only. Derived state -- ServiceEdge,
ServiceNode, their baselines, Incident and Event history -- is never
touched here: an incident that happened yesterday should still show
up in the incident list and its own evidence today, even after the
raw spans that fed it have aged out.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete

from app.models.telemetry import MetricPoint, Span


def prune_old_telemetry(db, workspace_id: UUID, older_than_hours: int) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)

    spans_deleted = db.execute(
        delete(Span).where(Span.workspace_id == workspace_id, Span.started_at < cutoff)
    ).rowcount
    metrics_deleted = db.execute(
        delete(MetricPoint).where(MetricPoint.workspace_id == workspace_id, MetricPoint.recorded_at < cutoff)
    ).rowcount
    db.commit()

    return {"spans_deleted": spans_deleted, "metrics_deleted": metrics_deleted, "cutoff": cutoff.isoformat()}