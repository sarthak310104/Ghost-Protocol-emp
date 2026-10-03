"""
Config drift detection for incident evidence.

The problem this exists to solve: a naive "what changed in the deploy
right before the incident" check has a real blind spot. If config key A
changed two deployments ago and looked completely fine on its own, and
key B changed in the most recent deployment, a fixed recent-deploy
window will only ever surface B -- even if the actual problem is that
A's new value and B's new value are incompatible together. A looked
healthy in isolation; the only way to catch it is to keep looking back
far enough to still see it, no matter how many deploys ago it was.

That rules out anchoring to a fixed, recent window -- by deploy count
or by calendar time -- which breaks in two different ways depending on
the company's deploy cadence: a weekly-deploy service dragging in many
months of mostly-irrelevant history, or an every-few-hours service
whose window might not even reach back to the last deploy that touched
config at all. The fix is to not count deploys in the first place --
only count actual value changes, per key. A deploy that didn't touch a
given key costs that key nothing; only a deploy that changed the key's
value gets charged against how far back we're allowed to look for it.
That makes the whole thing cadence-independent: it doesn't matter
whether a service deploys hourly or weekly, only how often its config
actually moves.

Ghost's job stops at surfacing this list as evidence. It does not, and
should not, claim that any one key (or combination of keys) caused the
incident -- that's an interaction/causal claim with no model behind it
here, same reasoning that kept the sandboxed what-if simulator out of
scope. Attribution is left to whatever's reading this evidence (a
human on the incident page, or the configured external reasoning
service) -- see app/simulation/engine.py's docstring for the same line
being drawn on the simulation side.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.deployment import Deployment

# Not a lookback window in the drift sense above -- this bounds how
# many of a service's past deployments we're willing to scan per
# service to find each key's last differing value, purely so one
# service with an enormous deployment history can't make this an
# unbounded table scan. A key whose value hasn't changed within this
# many *snapshot-bearing* deployments is reported as stable, not
# flagged -- which is the correct, honest answer: we have no evidence
# it changed recently, we simply stopped looking before finding out
# either way.
_MAX_DEPLOYMENTS_SCANNED_PER_SERVICE = 200


@dataclass
class ConfigDrift:
    service_name: str
    key: str
    current_value: str | None  # None means the key was removed as of the latest snapshot
    previous_value: str | None  # None means the key didn't exist before (newly introduced)
    changed_at: datetime  # when the key first took its current value
    version_at_change: str  # that deployment's version string, for a human to cross-reference
    deployments_since_change: int  # how many snapshot-bearing deployments have landed since, including this one

    def to_dict(self) -> dict:
        return {
            "service_name": self.service_name,
            "key": self.key,
            "current_value": self.current_value,
            "previous_value": self.previous_value,
            "changed_at": self.changed_at.isoformat(),
            "version_at_change": self.version_at_change,
            "deployments_since_change": self.deployments_since_change,
        }


def _drift_for_service(deployments: list[Deployment]) -> list[ConfigDrift]:
    """
    `deployments` must already be filtered to one service, newest
    first, and capped to `_MAX_DEPLOYMENTS_SCANNED_PER_SERVICE`. Rows
    with no config_snapshot at all (a caller that never submitted one,
    or submitted one for some deploys but not others) are skipped --
    they're neither evidence of a change nor evidence of stability, so
    they shouldn't count as a "still the same value" data point either.
    """
    snapshot_rows = [d for d in deployments if d.config_snapshot is not None]
    if len(snapshot_rows) < 2:
        return []  # need at least a current and one prior snapshot to detect anything

    latest = snapshot_rows[0]
    all_keys = set(latest.config_snapshot) | {k for d in snapshot_rows[1:] for k in d.config_snapshot}

    drift: list[ConfigDrift] = []
    for key in sorted(all_keys):
        current_value = latest.config_snapshot.get(key)  # None if removed as of the latest deploy

        # Walk backward until we find the first (i.e. most recent)
        # prior snapshot where this key held something else -- that
        # boundary tells us both the previous value and how long the
        # current value has actually been in place.
        last_matching_idx = 0  # latest itself trivially "matches" its own current value
        found_change = False
        previous_value = None
        for idx in range(1, len(snapshot_rows)):
            value_here = snapshot_rows[idx].config_snapshot.get(key, None)
            if value_here != current_value:
                previous_value = value_here
                found_change = True
                break
            last_matching_idx = idx

        if not found_change:
            continue  # stable for as far back as we looked -- not drift, just not enough evidence either way

        changed_at_row = snapshot_rows[last_matching_idx]
        drift.append(ConfigDrift(
            service_name=changed_at_row.service_name,
            key=key,
            current_value=current_value,
            previous_value=previous_value,
            changed_at=changed_at_row.deployed_at,
            version_at_change=changed_at_row.version,
            deployments_since_change=last_matching_idx + 1,
        ))
    return drift


def _scan_query(workspace_id: uuid.UUID, service_name: str, as_of: datetime):
    """
    Shared between the sync and async entry points below -- `as_of` is
    normally an incident's started_at, so a deploy that happened
    *after* the incident started never gets treated as its cause.
    """
    return (
        select(Deployment)
        .where(
            Deployment.workspace_id == workspace_id,
            Deployment.service_name == service_name,
            Deployment.deployed_at <= as_of,
        )
        .order_by(Deployment.deployed_at.desc())
        .limit(_MAX_DEPLOYMENTS_SCANNED_PER_SERVICE)
    )


def compute_config_drift(
    db: Session,
    workspace_id: uuid.UUID,
    service_names: set[str],
    as_of: datetime,
) -> list[ConfigDrift]:
    """
    Sync entry point -- used from Celery tasks (see
    app/workers/tasks.py:diagnose_incident). For each service, every
    config key whose current value differs from a value it held in
    some earlier deployment -- regardless of how many deployments ago
    that was, as long as it's within
    _MAX_DEPLOYMENTS_SCANNED_PER_SERVICE snapshot-bearing deploys.
    """
    results: list[ConfigDrift] = []
    for service_name in sorted(service_names):
        rows = db.execute(_scan_query(workspace_id, service_name, as_of)).scalars().all()
        results.extend(_drift_for_service(list(rows)))
    return results


async def compute_config_drift_async(
    db,
    workspace_id: uuid.UUID,
    service_names: set[str],
    as_of: datetime,
) -> list[ConfigDrift]:
    """Async entry point -- used from FastAPI routes (see app/api/routes/incidents.py)."""
    results: list[ConfigDrift] = []
    for service_name in sorted(service_names):
        query_result = await db.execute(_scan_query(workspace_id, service_name, as_of))
        results.extend(_drift_for_service(list(query_result.scalars().all())))
    return results