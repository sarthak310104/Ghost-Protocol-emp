"""
app/deployments/drift.py's _drift_for_service is pure (no DB access --
callers fetch the rows first), so it's tested the same DB-free way as
the rest of the algorithmic core: construct Deployment rows directly,
no session needed.
"""
import uuid
from datetime import datetime, timedelta, timezone

from app.deployments.drift import _drift_for_service
from app.models.deployment import Deployment


def _deploy(version: str, hours_ago: float, config_snapshot: dict[str, str] | None) -> Deployment:
    return Deployment(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        service_name="checkout",
        version=version,
        deployed_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        config_snapshot=config_snapshot,
    )


def _newest_first(*deploys: Deployment) -> list[Deployment]:
    """Caller convenience -- write scenarios oldest-first, feed the function newest-first like a real query would."""
    return list(reversed(deploys))


def test_the_motivating_scenario_catches_both_keys_not_just_the_most_recent():
    """
    A changed two deploys ago and looked fine on its own; B changed in
    the most recent deploy and the incident showed up right after.
    A naive "what changed in the last deploy" check would only ever
    find B -- this is the whole point of the feature.
    """
    deploys = _newest_first(
        _deploy("v1", hours_ago=3, config_snapshot={"A": "x", "B": "y"}),
        _deploy("v2", hours_ago=2, config_snapshot={"A": "w", "B": "y"}),  # A changes, nothing breaks
        _deploy("v3", hours_ago=1, config_snapshot={"A": "w", "B": "z"}),  # B changes, incident follows
    )
    drift = {d.key: d for d in _drift_for_service(deploys)}

    assert set(drift) == {"A", "B"}
    assert drift["A"].previous_value == "x" and drift["A"].current_value == "w"
    assert drift["A"].deployments_since_change == 2  # still live for v2 AND v3
    assert drift["B"].previous_value == "y" and drift["B"].current_value == "z"
    assert drift["B"].deployments_since_change == 1  # only this deploy


def test_a_key_that_never_changes_is_not_reported():
    deploys = _newest_first(
        _deploy("v1", hours_ago=2, config_snapshot={"STABLE": "same"}),
        _deploy("v2", hours_ago=1, config_snapshot={"STABLE": "same"}),
    )
    assert _drift_for_service(deploys) == []


def test_a_key_that_reverts_to_its_old_value_is_still_reported_as_a_change():
    """
    The revert itself is a real, recent change-event -- not something
    to silently cancel out just because the value matches something
    further back. Ghost surfaces it; it's not claiming the revert was
    a fix or a regression.
    """
    deploys = _newest_first(
        _deploy("v1", hours_ago=3, config_snapshot={"K": "a"}),
        _deploy("v2", hours_ago=2, config_snapshot={"K": "b"}),
        _deploy("v3", hours_ago=1, config_snapshot={"K": "a"}),  # reverted back to v1's value
    )
    drift = {d.key: d for d in _drift_for_service(deploys)}
    assert drift["K"].current_value == "a"
    assert drift["K"].previous_value == "b"
    assert drift["K"].deployments_since_change == 1


def test_newly_introduced_key_is_reported_with_no_previous_value():
    deploys = _newest_first(
        _deploy("v1", hours_ago=2, config_snapshot={"OLD": "1"}),
        _deploy("v2", hours_ago=1, config_snapshot={"OLD": "1", "NEW_KEY": "2"}),
    )
    drift = {d.key: d for d in _drift_for_service(deploys)}
    assert set(drift) == {"NEW_KEY"}
    assert drift["NEW_KEY"].previous_value is None
    assert drift["NEW_KEY"].current_value == "2"


def test_removed_key_is_reported_with_none_as_current_value():
    deploys = _newest_first(
        _deploy("v1", hours_ago=2, config_snapshot={"GOING_AWAY": "1", "STAYS": "x"}),
        _deploy("v2", hours_ago=1, config_snapshot={"STAYS": "x"}),  # GOING_AWAY dropped
    )
    drift = {d.key: d for d in _drift_for_service(deploys)}
    assert set(drift) == {"GOING_AWAY"}
    assert drift["GOING_AWAY"].current_value is None
    assert drift["GOING_AWAY"].previous_value == "1"


def test_deploys_with_no_submitted_snapshot_are_skipped_not_treated_as_empty():
    """
    A deploy that never called with config_snapshot shouldn't look like
    "every key got cleared" -- it should just be invisible to drift
    detection, as if it weren't a snapshot-bearing deploy at all.
    """
    deploys = _newest_first(
        _deploy("v1", hours_ago=3, config_snapshot={"K": "a"}),
        _deploy("v2-no-snapshot", hours_ago=2, config_snapshot=None),
        _deploy("v3", hours_ago=1, config_snapshot={"K": "b"}),
    )
    drift = {d.key: d for d in _drift_for_service(deploys)}
    assert set(drift) == {"K"}
    assert drift["K"].previous_value == "a"
    # v2 submitted no snapshot, so it's invisible to this computation --
    # from drift detection's view the sequence is just v1(a) -> v3(b),
    # so "b" is first seen at v3, not at the real-world v2.
    assert drift["K"].version_at_change == "v3"


def test_fewer_than_two_snapshots_yields_no_drift():
    # A single snapshot has nothing to compare against.
    assert _drift_for_service([_deploy("v1", hours_ago=1, config_snapshot={"K": "a"})]) == []
    # No snapshots at all.
    assert _drift_for_service([_deploy("v1", hours_ago=1, config_snapshot=None)]) == []