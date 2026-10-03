"""
app/notifications/webhook.py's build_payload is pure (no DB or network
access), so it's tested the same DB-free way as the rest of this
codebase's algorithmic core. notify_incident_event itself (DB + an
outbound HTTP call) isn't unit tested here -- same boundary this
codebase draws elsewhere, e.g. _drift_for_service vs. the DB-touching
compute_config_drift in app/deployments/drift.py.
"""
import uuid
from datetime import datetime, timezone

from app.models.incident import Incident
from app.notifications.webhook import build_payload


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