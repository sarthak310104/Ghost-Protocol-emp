"""
Thin DB-touching shell around app/slo/budget.py's pure computation --
same split as app/reliability/trends.py and app/deployments/drift.py:
fetch the rows, hand them to the pure function, return the result.
Sync + async entry points for the same reason those two have both:
sync is available to a Celery task (the burn-rate alert check, added
alongside this), async is what the FastAPI route awaits.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.slo import ServiceSLIRollup, SLODefinition
from app.slo.budget import HourlyCount, SLOStatus, compute_slo_status


def _rollup_query(workspace_id: uuid.UUID, service_name: str, window_days: int, now: datetime):
    cutoff = now - timedelta(days=window_days)
    return (
        select(ServiceSLIRollup)
        .where(
            ServiceSLIRollup.workspace_id == workspace_id,
            ServiceSLIRollup.service_name == service_name,
            ServiceSLIRollup.hour_bucket >= cutoff,
        )
        .order_by(ServiceSLIRollup.hour_bucket.desc())
    )


def _status_from_rollups(definition: SLODefinition, rollups: list[ServiceSLIRollup]) -> SLOStatus:
    # rollups is ordered most-recent-first (see _rollup_query) -- the
    # first element, if any, is the most recent hour, used for the
    # burn-rate signal; all of them together form the window total.
    window_counts = [HourlyCount(total_count=r.total_count, error_count=r.error_count) for r in rollups]
    most_recent = window_counts[0] if window_counts else None
    return compute_slo_status(
        service_name=definition.service_name,
        target_percent=definition.target_percent,
        window_days=definition.window_days,
        window_rollups=window_counts,
        most_recent_hour=most_recent,
    )


def compute_all_slo_statuses(db, workspace_id: uuid.UUID) -> list[SLOStatus]:
    """Sync entry point -- used by the hourly burn-rate alert check."""
    now = datetime.now(timezone.utc)
    definitions = db.execute(select(SLODefinition).where(SLODefinition.workspace_id == workspace_id)).scalars().all()
    statuses = []
    for definition in definitions:
        rollups = db.execute(_rollup_query(workspace_id, definition.service_name, definition.window_days, now)).scalars().all()
        statuses.append(_status_from_rollups(definition, list(rollups)))
    return statuses


async def compute_all_slo_statuses_async(db, workspace_id: uuid.UUID) -> list[SLOStatus]:
    """Async entry point -- used by the FastAPI route."""
    now = datetime.now(timezone.utc)
    result = await db.execute(select(SLODefinition).where(SLODefinition.workspace_id == workspace_id))
    definitions = result.scalars().all()
    statuses = []
    for definition in definitions:
        rows = await db.execute(_rollup_query(workspace_id, definition.service_name, definition.window_days, now))
        statuses.append(_status_from_rollups(definition, list(rows.scalars().all())))
    return statuses