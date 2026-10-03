"""
Hourly burn-rate check: for every SLODefinition in a workspace,
computes its current status and fires a webhook alert through the same
delivery path as incident notifications (app/notifications/webhook.py)
when it's burning fast.

Cooldown, not a fire-every-hour digest -- the whole point, per the
product decision behind this feature, is that the webhook behaves like
a push alert ("tell me when something's actually wrong"), not a
recurring status report nobody asked for. SLODefinition.alert_fired_at
is the state: null means "not currently alerting," set means "already
notified, don't repeat." A definition only re-fires after the burn
clears (is_fast_burning goes false) and then trips again -- so a
sustained multi-hour burn gets exactly one notification, not one every
hour it remains ongoing.

Runs from the same hourly tick as the SLI rollup (app/api/routes/internal.py),
after the rollup so this hour's data is already in before computing
status from it.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.slo import SLODefinition
from app.models.workspace import Workspace
from app.notifications.webhook import notify_slo_burn
from app.slo.status import compute_all_slo_statuses


def check_slo_burn_rates(db: Session, workspace_id: uuid.UUID) -> int:
    """Returns how many burn-rate alerts were fired for this workspace this run."""
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        return 0

    statuses_by_service = {s.service_name: s for s in compute_all_slo_statuses(db, workspace_id)}
    definitions = db.execute(
        select(SLODefinition).where(SLODefinition.workspace_id == workspace_id)
    ).scalars().all()

    fired = 0
    for definition in definitions:
        status = statuses_by_service.get(definition.service_name)
        if status is None:
            continue

        if status.is_fast_burning and definition.alert_fired_at is None:
            if workspace.notification_webhook_url:
                notify_slo_burn(db, workspace, status)
                fired += 1
            # Cooldown starts here regardless of whether a webhook was
            # actually configured to receive it -- otherwise an
            # unconfigured workspace would retry this same burn every
            # hour for no reason. Configuring a webhook mid-burn means
            # this particular burn won't alert retroactively; it'll
            # alert on the next one.
            definition.alert_fired_at = datetime.now(timezone.utc)
            db.commit()
        elif not status.is_fast_burning and definition.alert_fired_at is not None:
            # Burn cleared -- reset the cooldown so a future burn alerts again.
            definition.alert_fired_at = None
            db.commit()

    return fired


def check_all_workspaces_slo_burn_rates(db: Session) -> int:
    """Convenience wrapper for the hourly tick -- every workspace, one pass."""
    workspace_ids = db.execute(select(Workspace.id)).scalars().all()
    return sum(check_slo_burn_rates(db, ws_id) for ws_id in workspace_ids)