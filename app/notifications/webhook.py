"""
Outbound notifications. Ghost Protocol detects incidents and tracks
SLO burn rates but has no way to tell anyone short of someone watching
the dashboard -- this closes that gap with a single workspace-configured
webhook URL (Workspace.notification_webhook_url), POSTed a JSON payload
on incident open/resolve and on SLO fast-burn.

Deliberately one URL, not a per-provider integration list. Every
payload this module sends carries a top-level "text" one-liner that a
Slack Incoming Webhook accepts as-is (Slack's basic webhook contract is
just {"text": "..."}), plus a structured object for anything that wants
to parse it properly -- a generic webhook consumer, a custom relay,
etc. One delivery path covers both event kinds without Ghost Protocol
needing to know or care which kind of destination it's talking to, the
same provider-agnostic instinct behind the ReasoningProvider HTTP
contract used for the external reasoning connection.

Best-effort, single attempt -- not retried. A webhook endpoint that's
down shouldn't turn into a retry storm against someone's infrastructure,
and the whole point of a notification is that it's timely; one that
finally lands minutes later after retries isn't much better than one
that never lands. Delivery outcome (success or failure, with the
response status/error) is logged as a PipelineEvent, the same
per-workspace observability log the Pipeline Health page already reads
from -- a failed delivery is visible there for free, no separate
notification-history page needed.
"""
import uuid

from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.pipeline_event import PipelineEvent
from app.models.workspace import Workspace
from app.slo.budget import SLOStatus

_REQUEST_TIMEOUT_SECONDS = 5.0

_EVENT_VERBS = {
    "incident_opened": "opened",
    "incident_resolved": "resolved",
}


def build_payload(incident: Incident, event: str) -> dict:
    """Pure -- no DB or network access, so this is part of the testable core."""
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


def build_slo_burn_payload(status: SLOStatus) -> dict:
    """
    Pure, same reasoning as build_payload above. Only called once
    is_fast_burning is already True (see app/slo/alerts.py), so this
    doesn't re-check that -- it just formats whatever status it's given.
    """
    remaining = status.error_budget_remaining_percent
    remaining_text = "n/a" if remaining is None else f"{remaining:.0f}%"
    burn = status.burn_rate_1h
    burn_text = "inf" if burn == float("inf") else f"{burn:.1f}x" if burn is not None else "n/a"
    return {
        "event": "slo_burn_rate_critical",
        "text": (
            f"[SLO] {status.service_name} is burning its error budget {burn_text} faster than sustainable "
            f"(target {status.target_percent}% over {status.window_days}d, {remaining_text} budget remaining)"
        ),
        "slo": {
            "service_name": status.service_name,
            "target_percent": status.target_percent,
            "window_days": status.window_days,
            "actual_percent": status.actual_percent,
            "error_budget_remaining_percent": remaining,
            "burn_rate_1h": None if burn == float("inf") else burn,
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


def _deliver(db: Session, workspace: Workspace, payload: dict, log_label: str) -> None:
    """
    Shared delivery mechanics for both event kinds this module sends --
    the httpx call and the PipelineEvent logging are identical either
    way, only the payload and the label in the logged detail differ.

    httpx is imported here, not at module level -- requirements-test.txt
    deliberately excludes it (see that file's own comment), since the
    build_*_payload functions above are the only parts of this module
    the test suite needs, and they have no network dependency at all. A
    module-level import would have dragged httpx into every test
    collection run just to reach those pure functions, which is exactly
    what broke CI once already: ModuleNotFoundError on a dependency the
    test suite never actually uses.
    """
    import httpx

    url = workspace.notification_webhook_url
    if not is_sendable_webhook_url(url):
        db.add(PipelineEvent(
            workspace_id=workspace.id, kind="notification_delivery", is_error=True,
            detail=f"{log_label} skipped -- configured webhook URL is not http(s)",
        ))
        db.commit()
        return

    try:
        response = httpx.post(url, json=payload, timeout=_REQUEST_TIMEOUT_SECONDS)
        if response.status_code >= 400:
            db.add(PipelineEvent(
                workspace_id=workspace.id, kind="notification_delivery", is_error=True,
                detail=f"{log_label} rejected by webhook: HTTP {response.status_code}",
            ))
        else:
            db.add(PipelineEvent(
                workspace_id=workspace.id, kind="notification_delivery", is_error=False,
                detail=f"{log_label} delivered",
            ))
    except httpx.HTTPError as exc:
        db.add(PipelineEvent(
            workspace_id=workspace.id, kind="notification_delivery", is_error=True,
            detail=f"{log_label} failed: {exc}",
        ))
    db.commit()


def notify_incident_event(db: Session, incident_id: uuid.UUID, event: str) -> None:
    """
    Sync, called from a Celery task. Silently no-ops if the workspace
    has no webhook configured -- this is meant to be dispatched
    unconditionally from the incident lifecycle, not gated by the
    caller checking configuration first.
    """
    incident = db.get(Incident, incident_id)
    if incident is None:
        return

    workspace = db.get(Workspace, incident.workspace_id)
    if workspace is None or not workspace.notification_webhook_url:
        return

    payload = build_payload(incident, event)
    _deliver(db, workspace, payload, log_label=f"{event} notification for incident {incident.id}")


def notify_slo_burn(db: Session, workspace: Workspace, status: SLOStatus) -> None:
    """
    Sync, called from the hourly burn-rate check (app/slo/alerts.py),
    which already holds the Workspace row and has already confirmed
    status.is_fast_burning -- unlike notify_incident_event, there's no
    separate ID to look up here.
    """
    if not workspace.notification_webhook_url:
        return
    payload = build_slo_burn_payload(status)
    _deliver(db, workspace, payload, log_label=f"SLO burn-rate alert for {status.service_name}")