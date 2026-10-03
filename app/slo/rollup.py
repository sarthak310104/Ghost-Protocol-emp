"""
Hourly SLI rollup: folds the hour of raw spans that's about to age out
of ghost_telemetry_retention_hours into a durable per-service summary
row (ServiceSLIRollup) before that hour's spans are pruned.

Must run before prune_old_telemetry in the same tick -- see
app/api/routes/internal.py, which wires the ordering. If the ordering
were reversed, the hour this task means to summarize would already be
gone by the time it queries for it.

Idempotent by design: upserts on the (workspace_id, service_name,
hour_bucket) unique constraint, so re-running it for an hour that's
already been rolled up (e.g. a retried tick) just overwrites with the
same counts rather than double-counting.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.slo import ServiceSLIRollup
from app.models.telemetry import Span


def _hour_floor(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def rollup_sli_for_hour(db: Session, workspace_id: uuid.UUID, hour_bucket: datetime) -> int:
    """
    Aggregates spans in [hour_bucket, hour_bucket + 1h) into one
    ServiceSLIRollup row per service_name seen in that hour. Returns
    the number of (service) rollup rows written.
    """
    hour_bucket = _hour_floor(hour_bucket)
    hour_end = hour_bucket + timedelta(hours=1)

    rows = db.execute(
        select(
            Span.service_name,
            func.count().label("total_count"),
            func.count().filter(Span.status_code == "ERROR").label("error_count"),
        )
        .where(
            Span.workspace_id == workspace_id,
            Span.started_at >= hour_bucket,
            Span.started_at < hour_end,
        )
        .group_by(Span.service_name)
    ).all()

    for service_name, total_count, error_count in rows:
        stmt = pg_insert(ServiceSLIRollup).values(
            workspace_id=workspace_id,
            service_name=service_name,
            hour_bucket=hour_bucket,
            total_count=total_count,
            error_count=error_count,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["workspace_id", "service_name", "hour_bucket"],
            set_={"total_count": stmt.excluded.total_count, "error_count": stmt.excluded.error_count},
        )
        db.execute(stmt)

    db.commit()
    return len(rows)


def rollup_sli_for_last_hour(db: Session, workspace_id: uuid.UUID) -> int:
    """Convenience wrapper: rolls up the hour that just ended, as called from the hourly tick."""
    previous_hour = _hour_floor(datetime.now(timezone.utc)) - timedelta(hours=1)
    return rollup_sli_for_hour(db, workspace_id, previous_hour)