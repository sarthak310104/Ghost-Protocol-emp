"""
app/notifications/webhook.py's build_payload and build_slo_burn_payload
are pure (no DB or network access), so they're tested the same DB-free
way as the rest of this codebase's algorithmic core. notify_incident_event
and notify_slo_burn themselves (DB + an outbound HTTP call) aren't unit
tested here -- same boundary this codebase draws elsewhere, e.g.
_drift_for_service vs. the DB-touching compute_config_drift in
app/deployments/drift.py.
"""
import uuid
from datetime import datetime, timezone

from app.models.incident import Incident
from app.notifications.webhook import build_payload, build_slo_burn_payload
from app.slo.budget import SLOStatus


def _incident(status="open", severity="high", resolved_at=None) -> Incident:
    return Incident(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        title="Elevated latency on checkout",
        status=status,
        severity=severity,
        primary_service="checkout",
        started_at=datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc),
        resolved_at=resolved_at,
        evidence=[],
    )


def test_opened_payload_has_the_right_event_and_no_resolved_at():
    incident = _incident()
    payload = build_payload(incident, "incident_opened")
    assert payload["event"] == "incident_opened"
    assert payload["incident"]["id"] == str(incident.id)
    assert payload["incident"]["resolved_at"] is None
    assert "opened" in payload["text"]


def test_resolved_payload_includes_resolved_at():
    resolved_at = datetime(2026, 10, 3, 8, 30, tzinfo=timezone.utc)
    incident = _incident(status="resolved", resolved_at=resolved_at)
    payload = build_payload(incident, "incident_resolved")
    assert payload["event"] == "incident_resolved"
    assert payload["incident"]["resolved_at"] == resolved_at.isoformat()
    assert "resolved" in payload["text"]


def test_text_summary_includes_severity_title_and_service():
    incident = _incident(severity="critical")
    payload = build_payload(incident, "incident_opened")
    assert "CRITICAL" in payload["text"]
    assert incident.title in payload["text"]
    assert "checkout" in payload["text"]


def test_text_field_is_slack_webhook_compatible_shape():
    """A Slack Incoming Webhook accepts any payload with a top-level "text" string -- this is the whole contract."""
    payload = build_payload(_incident(), "incident_opened")
    assert isinstance(payload["text"], str)
    assert len(payload["text"]) > 0


def test_unknown_event_falls_back_to_the_raw_event_string():
    payload = build_payload(_incident(), "something_unexpected")
    assert payload["event"] == "something_unexpected"
    assert "something_unexpected" in payload["text"]


def _slo_status(**overrides) -> SLOStatus:
    defaults = dict(
        service_name="checkout",
        target_percent=99.9,
        window_days=30,
        total_count=10000,
        error_count=500,
        actual_percent=95.0,
        error_budget_total=10.0,
        error_budget_consumed=500,
        error_budget_remaining_percent=-4900.0,
        burn_rate_1h=50.0,
        is_fast_burning=True,
    )
    defaults.update(overrides)
    return SLOStatus(**defaults)


def test_slo_burn_payload_is_slack_compatible_shape():
    payload = build_slo_burn_payload(_slo_status())
    assert payload["event"] == "slo_burn_rate_critical"
    assert isinstance(payload["text"], str)
    assert "checkout" in payload["text"]
    assert payload["slo"]["service_name"] == "checkout"
    assert payload["slo"]["burn_rate_1h"] == 50.0


def test_slo_burn_payload_handles_infinite_burn_rate():
    """A 100% target with any error at all produces an infinite burn rate (see app/slo/budget.py) -- not JSON-serializable, so the payload must substitute something sendable."""
    status = _slo_status(target_percent=100.0, error_budget_total=0, error_budget_remaining_percent=None, burn_rate_1h=float("inf"))
    payload = build_slo_burn_payload(status)
    assert payload["slo"]["burn_rate_1h"] is None  # inf swapped for None, not left as a non-JSON float
    assert "inf" in payload["text"]
    assert "n/a" in payload["text"]  # budget-remaining text for the None case