"""
Substitutes for Celery beat's whole schedule in one endpoint, meant to
be pinged by an external free cron service (GitHub Actions, cron-job.org,
etc.) rather than requiring a persistent scheduler process -- see
GHOST_SYNC_MODE in app/core/config.py for why this exists at all.

Cadence is decided the same stateless way app/workers/demo_seeder.py
already does it: derived from the current wall-clock time rather than
anything stored, so it stays correct regardless of which process
happens to handle a given tick, or how many there are.
"""
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import select

from app.core.config import get_settings

router = APIRouter()


def _check_secret(header_secret: str | None, query_secret: str | None) -> None:
    settings = get_settings()
    if not settings.ghost_internal_secret:
        # Fails closed, not open -- an unconfigured secret means this
        # endpoint accepts nothing, not that it accepts everything.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Internal endpoint not configured")
    provided = header_secret or query_secret
    if not provided or not secrets.compare_digest(provided, settings.ghost_internal_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal secret")


@router.post("/internal/tick")
async def tick(
    x_internal_secret: str | None = Header(default=None),
    secret: str | None = None,
):
    """
    Accepts the secret via the X-Internal-Secret header (preferred) or
    a `?secret=` query parameter (fallback) -- some cron/webhook
    services make custom headers awkward or paywalled to configure, so
    the query param exists specifically so setup never blocks on
    finding the right UI element in a third-party dashboard.
    """
    _check_secret(x_internal_secret, secret)

    from app.db.sync_session import SyncSessionLocal
    from app.ingestion.retention import prune_old_telemetry
    from app.models.workspace import Workspace
    from app.workers.tasks import (
        refresh_all_reference_baselines,
        run_bottleneck_scan,
        scan_for_anomalies,
        seed_demo_workspace,
    )

    settings = get_settings()
    now = datetime.now(timezone.utc)
    ran = ["scan_for_anomalies"]
    scan_for_anomalies()

    # Roughly every 5 minutes, matching the original Celery beat cadence.
    if now.minute % 5 == 0:
        ran.append("run_bottleneck_scan")
        run_bottleneck_scan()

    # Top of the hour, matching the original hourly cadence. Retention
    # pruning rides along on the same cadence -- no need for it to run
    # more often than the data it's cleaning up accumulates meaningfully.
    if now.minute == 0:
        ran.append("refresh_all_reference_baselines")
        refresh_all_reference_baselines()

        ran.append("prune_old_telemetry")
        with SyncSessionLocal() as db:
            workspace_ids = db.execute(select(Workspace.id)).scalars().all()
            pruned = {
                str(ws_id): prune_old_telemetry(db, ws_id, settings.ghost_telemetry_retention_hours)
                for ws_id in workspace_ids
            }

    # No-ops immediately if GHOST_DEMO_WORKSPACE_ID isn't set.
    ran.append("seed_demo_workspace")
    seed_demo_workspace()

    result = {"ran": ran, "at": now.isoformat()}
    if "prune_old_telemetry" in ran:
        result["pruned"] = pruned
    return result
