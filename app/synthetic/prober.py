"""
Active synthetic monitoring's execution logic: the probe itself, the
SSRF guard that runs before any probe fires, and the state-transition
rules that turn a run of probe results into an opened or resolved
Incident.

Split the same way every other feature in this codebase is split: the
pure, testable decisions (is this status code a success? does this IP
resolve somewhere it shouldn't? has this check crossed its failure
threshold?) have zero DB/network imports and are unit tested directly.
The DB/network-touching wrapper around them (run_check) is verified
live instead, against a real Postgres + real HTTP target -- see the
module docstring on app/models/synthetic.py for why this feature
exists and what gap it closes.

SSRF threat model, decided deliberately rather than by default: Ghost
Protocol is a self-hosted, single-operator deployment (same framing
app/notifications/webhook.py's is_sendable_webhook_url already uses),
not multi-tenant SaaS taking arbitrary targets from untrusted users at
scale. Blocking all private/loopback ranges (RFC1918, localhost) would
break the feature's own legitimate use case -- a company registering a
check against its own internal service. So this does NOT block private
or loopback addresses. It DOES unconditionally block link-local
addresses (169.254.0.0/16, and the IPv6 equivalent), regardless of
threat model, because that range is never where a legitimate
application service lives and is specifically where cloud metadata
endpoints live (169.254.169.254 on AWS/GCP/Azure/DigitalOcean) -- a
zero-collateral-damage guard worth having unconditionally. The check
resolves the hostname via DNS first: a URL whose hostname string looks
perfectly ordinary can still resolve to a link-local address, so the
guard inspects the resolved IP, not the string.
"""
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from ipaddress import ip_address
from urllib.parse import urlparse

_MAX_STORED_RESULTS_PER_CHECK = 200  # bounded, raw history -- see app/models/synthetic.py


@dataclass
class ProbeOutcome:
    success: bool
    status_code: int | None
    latency_ms: float | None
    error: str | None


def resolve_blocks_link_local(hostname: str) -> tuple[bool, str | None]:
    """
    Pure except for the DNS lookup itself, which has no meaningful unit
    test (it talks to the resolver) -- the branching logic around it is
    what's tested, by calling this with hostnames that are already
    literal IPs (no real DNS involved) and asserting on the result.

    Returns (blocked, reason). A hostname that fails to resolve at all
    is not blocked here -- that's a connection failure, reported by the
    probe itself as a normal failed check, not a security rejection.
    """
    try:
        # getaddrinfo, not gethostbyname -- covers AAAA/IPv6 results too,
        # not just A/IPv4.
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, None

    for info in infos:
        raw_ip = info[4][0]
        try:
            parsed = ip_address(raw_ip)
        except ValueError:
            continue
        if parsed.is_link_local:
            return True, (
                f"resolves to a link-local address ({raw_ip}) -- this includes cloud "
                "metadata endpoints (e.g. 169.254.169.254) and is blocked regardless "
                "of deployment model"
            )
    return False, None


def validate_check_url(url: str) -> str | None:
    """
    Pure. Returns an error string if the URL should be rejected at
    registration time, or None if it's fine to save. Separate from
    resolve_blocks_link_local so a malformed URL (no hostname at all)
    gets a clear error instead of a confusing DNS failure.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "URL must start with http:// or https://"
    if not parsed.hostname:
        return "URL has no hostname"
    blocked, reason = resolve_blocks_link_local(parsed.hostname)
    if blocked:
        return f"Target not allowed: {reason}"
    return None


def classify_outcome(
    status_code: int | None, latency_ms: float | None, error: str | None,
    expected_status_min: int, expected_status_max: int,
) -> ProbeOutcome:
    """
    Pure. A transport-level failure (error is not None) is always a
    failure regardless of status_code, since there won't be one. A
    response outside the expected range is a failure even though the
    request itself succeeded -- e.g. a 500 is a successful HTTP
    round-trip carrying a failing application.
    """
    if error is not None or status_code is None:
        return ProbeOutcome(success=False, status_code=status_code, latency_ms=latency_ms, error=error)
    success = expected_status_min <= status_code <= expected_status_max
    return ProbeOutcome(success=success, status_code=status_code, latency_ms=latency_ms, error=None)


@dataclass
class StateTransition:
    new_consecutive_failures: int
    should_open_incident: bool
    should_resolve_incident: bool


def compute_state_transition(
    outcome_success: bool, consecutive_failures: int, failure_threshold: int, open_incident_id: uuid.UUID | None,
) -> StateTransition:
    """
    Pure. Same cooldown shape as SLODefinition.alert_fired_at /
    app/slo/alerts.py: a null/None open_incident_id means "not
    currently alerting," a set one means "already open, don't
    duplicate." Crossing the threshold is the only moment an incident
    opens; the very first success after that is the only moment it
    resolves -- every failure after the threshold, and every success
    before an incident is open, is a no-op transition.
    """
    if outcome_success:
        return StateTransition(
            new_consecutive_failures=0,
            should_open_incident=False,
            should_resolve_incident=open_incident_id is not None,
        )

    new_failures = consecutive_failures + 1
    should_open = new_failures >= failure_threshold and open_incident_id is None
    return StateTransition(
        new_consecutive_failures=new_failures,
        should_open_incident=should_open,
        should_resolve_incident=False,
    )


def run_check(db, check) -> ProbeOutcome:
    """
    DB/network-touching wrapper -- not part of the pure core above, not
    unit tested directly (verified live instead, per this module's own
    docstring). httpx imported lazily, same convention as
    app/notifications/webhook.py's _deliver, so requirements-test.txt
    (which excludes httpx) never needs it to collect the pure-function
    tests in tests/test_synthetic_prober.py.

    Mutates `check` in place and writes a SyntheticCheckResult row, but
    does not commit -- the caller (app/workers/tasks.py or the tick
    route) owns the transaction boundary, same as every other
    DB-touching helper in this codebase.
    """
    import httpx

    from app.models.incident import Event, Incident
    from app.models.synthetic import SyntheticCheckResult
    from app.notifications.webhook import notify_incident_event

    validation_error = validate_check_url(check.url)
    if validation_error is not None:
        outcome = ProbeOutcome(success=False, status_code=None, latency_ms=None, error=validation_error)
    else:
        try:
            response = httpx.request(check.method, check.url, timeout=check.timeout_seconds)
            latency_ms = response.elapsed.total_seconds() * 1000
            outcome = classify_outcome(
                response.status_code, latency_ms, None,
                check.expected_status_min, check.expected_status_max,
            )
        except httpx.HTTPError as exc:
            outcome = classify_outcome(None, None, str(exc), check.expected_status_min, check.expected_status_max)

    now = datetime.now(timezone.utc)
    check.last_probed_at = now
    db.add(SyntheticCheckResult(
        check_id=check.id, ran_at=now, success=outcome.success,
        status_code=outcome.status_code, latency_ms=outcome.latency_ms, error=outcome.error,
    ))

    transition = compute_state_transition(
        outcome.success, check.consecutive_failures, check.failure_threshold, check.open_incident_id,
    )
    check.consecutive_failures = transition.new_consecutive_failures

    if transition.should_open_incident:
        incident = Incident(
            workspace_id=check.workspace_id,
            title=f"Synthetic check failing: {check.name}",
            status="open",
            severity="high",
            primary_service=check.name,
            evidence=[{
                "kind": "synthetic_check", "check_id": str(check.id), "url": check.url,
                "consecutive_failures": check.consecutive_failures,
                "last_status_code": outcome.status_code, "last_error": outcome.error,
            }],
        )
        db.add(incident)
        db.flush()  # need incident.id before referencing it
        db.add(Event(
            incident_id=incident.id, kind="synthetic_check_failed",
            message=f"{check.name} failed {check.consecutive_failures} consecutive probes against {check.url}",
        ))
        check.open_incident_id = incident.id
        db.flush()
        notify_incident_event(db, incident.id, "incident_opened")
    elif transition.should_resolve_incident:
        incident = db.get(Incident, check.open_incident_id)
        if incident is not None:
            incident.status = "resolved"
            incident.resolved_at = now
            db.add(Event(
                incident_id=incident.id, kind="synthetic_check_recovered",
                message=f"{check.name} succeeded again -- resolving",
            ))
            db.flush()
            notify_incident_event(db, incident.id, "incident_resolved")
        check.open_incident_id = None

    _prune_old_results(db, check.id)
    return outcome


def _prune_old_results(db, check_id: uuid.UUID) -> None:
    """
    Keeps only the most recent _MAX_STORED_RESULTS_PER_CHECK rows per
    check -- bounded by definition (see app/models/synthetic.py), so a
    simple keep-newest-N delete is enough; no time-based retention
    setting needed the way raw telemetry has one.
    """
    from sqlalchemy import select

    from app.models.synthetic import SyntheticCheckResult

    ids_to_keep = db.execute(
        select(SyntheticCheckResult.id)
        .where(SyntheticCheckResult.check_id == check_id)
        .order_by(SyntheticCheckResult.ran_at.desc())
        .limit(_MAX_STORED_RESULTS_PER_CHECK)
    ).scalars().all()
    if not ids_to_keep:
        return
    db.execute(
        SyntheticCheckResult.__table__.delete().where(
            SyntheticCheckResult.check_id == check_id,
            SyntheticCheckResult.id.notin_(ids_to_keep),
        )
    )


def run_due_checks(db, workspace_id: uuid.UUID | None = None) -> int:
    """
    Runs every SyntheticCheck whose own interval_seconds has elapsed
    since last_probed_at -- NOT gated by the tick's own
    now.minute % 2 == 0 cadence the way scan_for_anomalies/
    seed_demo_workspace are (see app/api/routes/internal.py). Those are
    fixed-cadence background jobs; a check's interval is a per-check
    setting the user configured, so it has to be evaluated against each
    check's own clock, independent of how often the tick itself fires.
    Called every tick; most calls here will be a no-op for most checks.
    """
    from sqlalchemy import select

    from app.models.synthetic import SyntheticCheck

    now = datetime.now(timezone.utc)
    query = select(SyntheticCheck)
    if workspace_id is not None:
        query = query.where(SyntheticCheck.workspace_id == workspace_id)
    checks = db.execute(query).scalars().all()

    ran = 0
    for check in checks:
        if check.last_probed_at is not None:
            elapsed = (now - check.last_probed_at).total_seconds()
            if elapsed < check.interval_seconds:
                continue
        run_check(db, check)
        db.commit()
        ran += 1
    return ran