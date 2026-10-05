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
    from app.slo.alerts import check_all_workspaces_slo_burn_rates
    from app.slo.rollup import rollup_sli_for_last_hour
    from app.synthetic.prober import run_due_checks
    from app.workers.tasks import (
        refresh_all_reference_baselines,
        run_bottleneck_scan,
        scan_for_anomalies,
        seed_demo_workspace,
    )

    settings = get_settings()
    now = datetime.now(timezone.utc)
    ran = []

    # Every 2 minutes, not every tick. Both this and seed_demo_workspace
    # below (which does its own unconditional span inserts + graph
    # update + internal anomaly scan) used to run on literally every
    # call -- with an external cron pinging at ~1-minute granularity,
    # that meant continuous DB activity with no gap ever, which is
    # exactly what exhausted Neon's free-tier compute-hours once
    # already (see the deployment history/postmortem for that outage).
    # A stateless wall-clock gate, same pattern as the 5-minute and
    # hourly blocks below, gives Postgres real idle gaps between ticks
    # so its auto-suspend can actually fire. Detection latency goes
    # from effectively instant to up to ~2 minutes -- an acceptable
    # trade for not risking the whole demo going down for a month again.
    if now.minute % 2 == 0:
        ran.append("scan_for_anomalies")
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

        # Must run before prune_old_telemetry below: it summarizes the
        # hour of spans that just completed into a row that survives
        # pruning (see app/slo/rollup.py's module docstring). Reversing
        # this order would mean the data it's meant to summarize is
        # already gone by the time it queries for it.
        ran.append("rollup_sli")
        with SyncSessionLocal() as db:
            workspace_ids_for_rollup = db.execute(select(Workspace.id)).scalars().all()
            for ws_id in workspace_ids_for_rollup:
                rollup_sli_for_last_hour(db, ws_id)

        # After the rollup above, so this hour's counts are already in
        # before computing burn rate from them.
        ran.append("check_slo_burn_rates")
        with SyncSessionLocal() as db:
            check_all_workspaces_slo_burn_rates(db)

        ran.append("prune_old_telemetry")
        with SyncSessionLocal() as db:
            workspace_ids = db.execute(select(Workspace.id)).scalars().all()
            pruned = {
                str(ws_id): prune_old_telemetry(db, ws_id, settings.ghost_telemetry_retention_hours)
                for ws_id in workspace_ids
            }

    # Same 2-minute gate as scan_for_anomalies above, and for the same
    # reason -- this is the real driver of continuous DB writes in the
    # live deployment (span inserts, a graph update, and its own
    # internal anomaly scan, all unconditional whenever
    # GHOST_DEMO_WORKSPACE_ID is set, which it is in production). Known
    # trade: a spike-onset incident can now take up to ~2 minutes to
    # appear instead of showing up on the very next tick, and the
    # 90-second deployment-recording window at spike onset (see that
    # function's own comment) can occasionally be missed entirely
    # between two 2-minute-apart calls -- acceptable for a demo; not
    # worth re-risking the whole thing going down over.
    if now.minute % 2 == 0:
        ran.append("seed_demo_workspace")
        seed_demo_workspace()

    # Not gated to even minutes like the two blocks above -- each
    # SyntheticCheck has its own user-configured interval_seconds and
    # self-gates against its own last_probed_at (see
    # app/synthetic/prober.run_due_checks), independent of how often
    # this tick itself fires. Runs every call; a no-op for any check
    # whose interval hasn't elapsed yet.
    ran.append("run_due_checks")
    with SyncSessionLocal() as db:
        checks_ran = run_due_checks(db)

    result = {"ran": ran, "at": now.isoformat(), "synthetic_checks_ran": checks_ran}
    if "prune_old_telemetry" in ran:
        result["pruned"] = pruned
    return result