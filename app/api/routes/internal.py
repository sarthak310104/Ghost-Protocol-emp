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

from app.core.config import get_settings

router = APIRouter()


def _check_secret(x_internal_secret: str | None) -> None:
    settings = get_settings()
    if not settings.ghost_internal_secret:
        # Fails closed, not open -- an unconfigured secret means this
        # endpoint accepts nothing, not that it accepts everything.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Internal endpoint not configured")
    if not x_internal_secret or not secrets.compare_digest(x_internal_secret, settings.ghost_internal_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal secret")


@router.post("/internal/tick")
async def tick(x_internal_secret: str | None = Header(default=None)):
    _check_secret(x_internal_secret)

    from app.workers.tasks import (
        refresh_all_reference_baselines,
        run_bottleneck_scan,
        scan_for_anomalies,
        seed_demo_workspace,
    )

    now = datetime.now(timezone.utc)
    ran = ["scan_for_anomalies"]
    scan_for_anomalies()

    # Roughly every 5 minutes, matching the original Celery beat cadence.
    if now.minute % 5 == 0:
        ran.append("run_bottleneck_scan")
        run_bottleneck_scan()

    # Top of the hour, matching the original hourly cadence.
    if now.minute == 0:
        ran.append("refresh_all_reference_baselines")
        refresh_all_reference_baselines()

    # No-ops immediately if GHOST_DEMO_WORKSPACE_ID isn't set.
    ran.append("seed_demo_workspace")
    seed_demo_workspace()

    return {"ran": ran, "at": now.isoformat()}