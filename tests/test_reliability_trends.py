"""
app/reliability/trends.py's _bucket_incidents is pure (no DB access --
callers fetch the rows first), so it's tested the same DB-free way as
the rest of the algorithmic core: construct Incident rows directly, no
session needed.
"""
import uuid
from datetime import datetime, timedelta, timezone

from app.reliability.trends import _bucket_incidents
from app.models.incident import Incident

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def _incident(service: str, days_ago: float, severity: str = "medium", resolved_after_seconds: float | None = None) -> Incident:
    started_at = NOW - timedelta(days=days_ago)
    resolved_at = started_at + timedelta(seconds=resolved_after_seconds) if resolved_after_seconds is not None else None
    return Incident(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        title="test incident",
        status="resolved" if resolved_at else "open",
        severity=severity,
        primary_service=service,
        started_at=started_at,
        last_seen_at=started_at,
        resolved_at=resolved_at,
        evidence=[],
    )


def test_incidents_land_in_the_correct_weekly_bucket():
    incidents = [
        _incident("checkout", days_ago=1),   # this week, weeks_ago=0
        _incident("checkout", days_ago=8),   # last week, weeks_ago=1
        _incident("checkout", days_ago=15),  # two weeks ago, weeks_ago=2
    ]
    bucketed = _bucket_incidents(incidents, weeks=4, now=NOW)
    weeks = {w.weeks_ago: w for w in bucketed["checkout"]}
    assert weeks[0].incident_count == 1
    assert weeks[1].incident_count == 1
    assert weeks[2].incident_count == 1
    assert weeks[3].incident_count == 0


def test_incidents_outside_the_lookback_window_are_excluded():
    incidents = [_incident("checkout", days_ago=100)]
    bucketed = _bucket_incidents(incidents, weeks=4, now=NOW)
    # The service never appears at all -- not a zero-filled entry -- since
    # nothing about it fell inside the requested window.
    assert bucketed == {}


def test_every_requested_week_is_present_even_with_zero_incidents():
    incidents = [_incident("checkout", days_ago=1)]
    bucketed = _bucket_incidents(incidents, weeks=6, now=NOW)
    assert [w.weeks_ago for w in bucketed["checkout"]] == [5, 4, 3, 2, 1, 0]  # oldest first
    assert bucketed["checkout"][-1].incident_count == 1  # weeks_ago=0 is last in oldest-first order


def test_severity_counts_tally_per_bucket():
    incidents = [
        _incident("checkout", days_ago=1, severity="high"),
        _incident("checkout", days_ago=2, severity="high"),
        _incident("checkout", days_ago=3, severity="low"),
    ]
    bucketed = _bucket_incidents(incidents, weeks=2, now=NOW)
    this_week = next(w for w in bucketed["checkout"] if w.weeks_ago == 0)
    assert this_week.severity_counts == {"high": 2, "low": 1}


def test_mttr_only_counts_resolved_incidents_and_computes_mean_and_median():
    incidents = [
        _incident("checkout", days_ago=1, resolved_after_seconds=60),
        _incident("checkout", days_ago=1, resolved_after_seconds=120),
        _incident("checkout", days_ago=1, resolved_after_seconds=300),
        _incident("checkout", days_ago=1),  # still open -- no MTTR contribution
    ]
    bucketed = _bucket_incidents(incidents, weeks=1, now=NOW)
    this_week = bucketed["checkout"][0]
    assert this_week.incident_count == 4
    assert this_week.resolved_count == 3
    assert this_week.mttr_mean_seconds == (60 + 120 + 300) / 3
    assert this_week.mttr_median_seconds == 120


def test_unresolved_only_bucket_has_no_mttr():
    incidents = [_incident("checkout", days_ago=1)]  # open, never resolved
    bucketed = _bucket_incidents(incidents, weeks=1, now=NOW)
    this_week = bucketed["checkout"][0]
    assert this_week.resolved_count == 0
    assert this_week.mttr_mean_seconds is None
    assert this_week.mttr_median_seconds is None


def test_services_are_bucketed_independently():
    incidents = [
        _incident("checkout", days_ago=1),
        _incident("payments-api", days_ago=1),
        _incident("payments-api", days_ago=1),
    ]
    bucketed = _bucket_incidents(incidents, weeks=1, now=NOW)
    assert bucketed["checkout"][0].incident_count == 1
    assert bucketed["payments-api"][0].incident_count == 2


def test_no_incidents_at_all_yields_empty_result():
    assert _bucket_incidents([], weeks=4, now=NOW) == {}