"""
Outbound incident notifications. Ghost Protocol detects and diagnoses
incidents but has no way to tell anyone it happened short of someone
watching the dashboard -- this closes that gap with a single
workspace-configured webhook URL (Workspace.notification_webhook_url),
POSTed a JSON payload on incident open and incident resolve.

Deliberately one URL, not a per-provider integration list. The payload
carries a top-level "text" one-liner that a Slack Incoming Webhook
accepts as-is (Slack's basic webhook contract is just {"text": "..."}),
plus a structured "incident" object for anything that wants to parse
it properly -- a generic webhook consumer, a custom relay, etc. One
delivery path covers both without Ghost Protocol needing to know or
care which kind of destination it's talking to, the same
provider-agnostic instinct behind the ReasoningProvider HTTP contract
used for the external reasoning connection.

Best-effort, single attempt -- not retried. A webhook endpoint that's
down shouldn't turn into a retry storm against someone's infrastructure,
and the whole point of an incident notification is that it's timely;
a notification that finally lands minutes later after retries isn't
much better than one that never lands. Delivery outcome (success or
failure, with the response status/error) is logged as a PipelineEvent,
the same per-workspace observability log the Pipeline Health page
already reads from -- a failed delivery is visible there for free,
no separate notification-history page needed.
"""
import uuid

from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.pipeline_event import PipelineEvent
from app.models.workspace import Workspace

_REQUEST_TIMEOUT_SECONDS = 5.0

_EVENT_VERBS = {
    "incident_opened": "opened",
    "incident_resolved": "resolved",
}


def build_payload(incident: Incident, event: str) -> dict:
    """Pure -- no DB or network access, so this is the testable part of the module."""
    verb = _EVENT_VERBS.get(event, event)
    return {
        "event": event,
        "text": f"[{incident.severity.upper()}] {incident.title} -- {verb} ({incident.primary_service})",
        "incident": {
            "id": str(incident.id),
            "title": incident.title,
            "status": incident.status,
            "severity": incident.severity,
            "primary_service": incident.primary_service,
            "started_at": incident.started_at.isoformat(),
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        },
    }


def is_sendable_webhook_url(url: str) -> bool:
    # Not a full SSRF defense (this is a self-hosted, single-operator
    # deployment, not a multi-tenant one taking arbitrary user input at
    # scale) -- just enough to reject an obviously malformed value
    # before spending a network call on it. Public (no leading
    # underscore) because app/api/routes/workspace.py reuses this same
    # check when a workspace sets the URL, so a bad value is rejected
    # at configuration time rather than only discovered later as a
    # string of failed delivery attempts in the pipeline-health log.
    return url.startswith("https://") or url.startswith("http://")


def notify_incident_event(db: Session, incident_id: uuid.UUID, event: str) -> None:
    """
    Sync, called from a Celery task. Silently no-ops if the workspace
    has no webhook configured -- this is meant to be dispatched
    unconditionally from the incident lifecycle, not gated by the
    caller checking configuration first.

    httpx is imported here, not at module level -- requirements-test.txt
    deliberately excludes it (see that file's own comment), since
    build_payload above is the only part of this module the test suite
    needs, and it has no network dependency at all. A module-level
    import would have dragged httpx into every test collection run
    just to reach that one pure function, which is exactly what broke
    CI: ModuleNotFoundError on a dependency the test suite never
    actually uses.
    """
    import httpx

    incident = db.get(Incident, incident_id)
    if incident is None:
        return

    workspace = db.get(Workspace, incident.workspace_id)
    if workspace is None or not workspace.notification_webhook_url:
        return

    url = workspace.notification_webhook_url
    if not is_sendable_webhook_url(url):
        db.add(PipelineEvent(
            workspace_id=workspace.id, kind="notification_delivery", is_error=True,
            detail=f"{event} notification for incident {incident.id} skipped -- configured webhook URL is not http(s)",
        ))
        db.commit()
        return

    payload = build_payload(incident, event)
    try:
        response = httpx.post(url, json=payload, timeout=_REQUEST_TIMEOUT_SECONDS)
        if response.status_code >= 400:
            db.add(PipelineEvent(
                workspace_id=workspace.id, kind="notification_delivery", is_error=True,
                detail=f"{event} notification for incident {incident.id} rejected by webhook: HTTP {response.status_code}",
            ))
        else:
            db.add(PipelineEvent(
                workspace_id=workspace.id, kind="notification_delivery", is_error=False,
                detail=f"{event} notification delivered for incident {incident.id}",
            ))
    except httpx.HTTPError as exc:
        db.add(PipelineEvent(
            workspace_id=workspace.id, kind="notification_delivery", is_error=True,
            detail=f"{event} notification for incident {incident.id} failed: {exc}",
        ))
    db.commit()