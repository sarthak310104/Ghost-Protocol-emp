import uuid
from datetime import datetime, timedelta, timezone

from celery.utils.log import get_task_logger
from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.dispatch import dispatch
from app.cohort.analysis import run_cohort_analysis
from app.db.sync_session import SyncSessionLocal
from app.graph.baseline import EdgeObservation, update_edge_baseline
from app.graph.reference import refresh_reference_baselines
from app.graph.repo import get_or_create_edge, get_or_create_node
from app.graph.topology import derive_edges
from app.incident.correlate import correlate_and_persist
from app.incident.detect import detect_edge_anomalies
from app.models.cohort import CohortDimension
from app.models.deployment import Deployment
from app.models.graph import ServiceEdge
from app.models.incident import Event, Incident, ReasoningResult
from app.models.telemetry import MetricPoint, Span
from app.models.workspace import Workspace
from app.simulation.engine import simulate_incident_resolution
from app.workers.demo_seeder import demo_cycle_is_spiking

# The reasoning-integration module is optional and may not be present
# in every deployment of this codebase. This import is soft: if it's
# missing, diagnose_incident degrades to "no reasoning integration
# configured" instead of crashing the worker on startup.
try:
    from app.reasoning.client import ReasoningNotConfigured, ReasoningServiceError, call_reasoning_service
    from app.reasoning.contract import DiagnosisRequest, EvidenceItem
    REASONING_AVAILABLE = True
except ImportError:
    REASONING_AVAILABLE = False

logger = get_task_logger(__name__)


def _ns_to_dt(unix_ns: int) -> datetime:
    return datetime.fromtimestamp(unix_ns / 1_000_000_000, tz=timezone.utc)


@celery_app.task(name="app.workers.tasks.ingest_spans_batch")
def ingest_spans_batch(workspace_id: str, spans: list[dict]) -> int:
    """Bulk-writes normalized spans, then hands the same batch to graph/baseline processing."""
    with SyncSessionLocal() as db:
        rows = [
            Span(
                id=uuid.UUID(s["id"]),
                workspace_id=uuid.UUID(s["workspace_id"]),
                trace_id=s["trace_id"],
                span_id=s["span_id"],
                parent_span_id=s["parent_span_id"],
                service_name=s["service_name"],
                span_name=s["span_name"],
                kind=s["kind"],
                started_at=_ns_to_dt(s["started_at_unix_ns"]),
                duration_ms=s["duration_ms"],
                status_code=s["status_code"],
                attributes=s["attributes"],
            )
            for s in spans
        ]
        db.add_all(rows)
        db.commit()

    dispatch(update_graph_and_baselines, workspace_id, spans)
    return len(rows)


@celery_app.task(name="app.workers.tasks.ingest_metrics_batch")
def ingest_metrics_batch(workspace_id: str, metrics: list[dict]) -> int:
    with SyncSessionLocal() as db:
        rows = [
            MetricPoint(
                id=uuid.UUID(m["id"]),
                workspace_id=uuid.UUID(m["workspace_id"]),
                service_name=m["service_name"],
                metric_name=m["metric_name"],
                value=m["value"],
                unit=m.get("unit"),
                recorded_at=_ns_to_dt(m["recorded_at_unix_ns"]),
                attributes=m["attributes"],
            )
            for m in metrics
        ]
        db.add_all(rows)
        db.commit()
    return len(rows)


@celery_app.task(name="app.workers.tasks.update_graph_and_baselines")
def update_graph_and_baselines(workspace_id: str, spans: list[dict]) -> int:
    """Discovers services/edges from this span batch and folds each observation into the fast baseline."""
    ws_id = uuid.UUID(workspace_id)
    edges = derive_edges(spans)

    services_seen = {s["service_name"] for s in spans}

    with SyncSessionLocal() as db:
        for service_name in services_seen:
            get_or_create_node(db, ws_id, service_name)

        for derived in edges:
            edge = get_or_create_edge(db, ws_id, derived.caller, derived.callee)
            update_edge_baseline(edge, EdgeObservation(duration_ms=derived.duration_ms, is_error=derived.is_error))

        db.commit()

    return len(edges)


@celery_app.task(name="app.workers.tasks.run_reference_baseline_refresh")
def run_reference_baseline_refresh(workspace_id: str) -> int:
    from app.bottleneck.reference import refresh_risk_reference_baselines

    with SyncSessionLocal() as db:
        edge_count = refresh_reference_baselines(db, uuid.UUID(workspace_id))
    with SyncSessionLocal() as db:
        # Same cadence, same task, separate DB session per call for the
        # same reason the rest of this file does it -- each helper
        # commits its own transaction rather than sharing one across two
        # unrelated units of work.
        refresh_risk_reference_baselines(db, uuid.UUID(workspace_id))
    return edge_count


@celery_app.task(name="app.workers.tasks.refresh_all_reference_baselines")
def refresh_all_reference_baselines() -> None:
    """
    Scheduled fan-out across every workspace (see celery beat config).
    Anomaly detection compares an edge's "current" EWMA against its
    "reference" baseline -- without this running periodically, an edge
    never gets a reference and scan_for_anomalies has nothing to compare
    against.
    """
    with SyncSessionLocal() as db:
        workspace_ids = db.execute(select(Workspace.id)).scalars().all()
    for ws_id in workspace_ids:
        dispatch(run_reference_baseline_refresh, str(ws_id))


@celery_app.task(name="app.workers.tasks.run_incident_simulation")
def run_incident_simulation(incident_id: str) -> None:
    """
    Ghost's own statistical simulation for one incident -- runs
    unconditionally as soon as the incident exists, with no dependency
    on any external reasoning service being configured, available, or
    successful. This is what backs GET /v1/incidents/{id}/evidence's
    simulation_results even in a deployment with no reasoning
    integration at all.

    Also attaches a cohort comparison for each affected edge, for any
    dimension the workspace has registered -- if a canary/gradual
    rollout happens to be running concurrently on that exact edge right
    now, this surfaces "here's what the two live cohorts actually show"
    alongside the mean-reversion projection, without needing anyone to
    ask for it separately.
    """
    inc_id = uuid.UUID(incident_id)
    with SyncSessionLocal() as db:
        incident = db.get(Incident, inc_id)
        if incident is None:
            return
        affected_edges = {(e["caller"], e["callee"]) for e in incident.evidence}
        simulation = simulate_incident_resolution(db, incident.workspace_id, incident.primary_service, affected_edges)

        dimensions = db.execute(
            select(CohortDimension).where(CohortDimension.workspace_id == incident.workspace_id)
        ).scalars().all()

        cohort_results = []
        for caller, callee in affected_edges:
            for dim in dimensions:
                result = run_cohort_analysis(db, incident.workspace_id, caller, callee, dim.attribute_key)
                # Only attach results that actually found something --
                # an edge with no cohort tagging on it shouldn't clutter
                # the output with "no data" entries for every registered
                # dimension that happens to not apply here.
                if result.cohorts:
                    cohort_results.append(result.to_dict())

        if cohort_results:
            simulation["cohort_comparisons"] = cohort_results

        incident.simulation = simulation
        db.commit()


_DIAGNOSIS_RETRY_COOLDOWN = timedelta(minutes=15)


def _should_retry_diagnosis(db, incident: Incident) -> bool:
    """
    For an incident that's still open but didn't just escalate: only
    worth retrying external reasoning if enough time has passed since
    the last attempt. Covers legitimate cases (reasoning wasn't
    configured yet and got fixed mid-incident, a transient outage on the
    reasoning service) without retrying every 30s for as long as an
    incident happens to stay open.
    """
    last_attempt = db.execute(
        select(Event.occurred_at).where(
            Event.incident_id == incident.id,
            Event.kind.in_(["diagnosis_started"]),
        ).order_by(Event.occurred_at.desc()).limit(1)
    ).scalar_one_or_none()
    if last_attempt is None:
        return True  # never actually attempted -- shouldn't happen if correlate always dispatches on creation, but safe default
    return datetime.now(timezone.utc) - last_attempt >= _DIAGNOSIS_RETRY_COOLDOWN


@celery_app.task(name="app.workers.tasks.scan_for_anomalies")
def scan_for_anomalies() -> None:
    """
    Runs on a schedule (see celery beat config) across every workspace.
    Detects anomalies against each edge's reference baseline, correlates
    them into incidents, and runs Ghost's own statistical simulation
    unconditionally (no reasoning service required) -- but only dispatches
    external diagnosis for a NEWLY opened incident, one that just
    escalated in severity, or one whose last diagnosis attempt is older
    than a cooldown window. Without that gating, an incident that stays
    open for many scan cycles would trigger one external reasoning call
    per cycle for as long as it remains open.
    """
    with SyncSessionLocal() as db:
        workspace_ids = db.execute(select(Workspace.id)).scalars().all()

    for ws_id in workspace_ids:
        with SyncSessionLocal() as db:
            edges = db.execute(select(ServiceEdge).where(ServiceEdge.workspace_id == ws_id)).scalars().all()
            anomalies = detect_edge_anomalies(edges)
            if not anomalies:
                continue

            results = correlate_and_persist(db, ws_id, anomalies)
            for incident, should_dispatch in results:
                dispatch(run_incident_simulation, str(incident.id))
                if should_dispatch or _should_retry_diagnosis(db, incident):
                    dispatch(diagnose_incident, str(incident.id))


@celery_app.task(name="app.workers.tasks.run_bottleneck_scan")
def run_bottleneck_scan() -> None:
    """Continuous structural-risk scan, independent of whether any incident is currently open."""
    from app.bottleneck.baseline import update_risk_baseline
    from app.bottleneck.engine import compute_bottlenecks
    from app.graph.repo import get_or_create_node

    with SyncSessionLocal() as db:
        workspace_ids = db.execute(select(Workspace.id)).scalars().all()

    for ws_id in workspace_ids:
        with SyncSessionLocal() as db:
            edges = db.execute(select(ServiceEdge).where(ServiceEdge.workspace_id == ws_id)).scalars().all()
            risks = compute_bottlenecks(edges)

            # Feed each service's own risk-score baseline (current EWMA +
            # Welford variance) on every scan -- this is what lets "is
            # this service unusually risky right now" eventually be
            # judged against ITS OWN history rather than one fixed
            # threshold applied uniformly to every service.
            for risk in risks:
                node = get_or_create_node(db, ws_id, risk.service)
                update_risk_baseline(node, risk.risk_score)
            db.commit()

            for risk in risks[:5]:
                logger.info("bottleneck_risk", extra={"workspace_id": str(ws_id), **risk.__dict__})


@celery_app.task(name="app.workers.tasks.diagnose_incident")
def diagnose_incident(incident_id: str) -> None:
    """
    Builds evidence from the incident, calls the workspace's configured
    external reasoning/analysis service (if any), then runs the
    simulation engine on the result. Ghost Protocol never retrieves
    documents or calls an LLM itself -- that's entirely the external
    service's concern.

    If app/reasoning/ isn't present in this build, this task records
    that outright and returns -- the incident, its evidence, and the
    simulation engine's own analysis (see simulate_incident_resolution,
    called independently of this task via the evidence API) remain fully
    available either way.
    """
    inc_id = uuid.UUID(incident_id)

    if not REASONING_AVAILABLE:
        with SyncSessionLocal() as db:
            incident = db.get(Incident, inc_id)
            if incident is not None:
                db.add(Event(
                    incident_id=incident.id,
                    kind="diagnosis_skipped",
                    message="No reasoning integration in this build -- evidence is available via /v1/incidents/{id}/evidence.",
                ))
                db.commit()
        return

    with SyncSessionLocal() as db:
        incident = db.get(Incident, inc_id)
        if incident is None:
            return
        workspace = db.get(Workspace, incident.workspace_id)

        incident.status = "diagnosing"
        db.add(Event(incident_id=incident.id, kind="diagnosis_started", message="Calling configured reasoning service."))
        db.commit()

        affected_services = {e["caller"] for e in incident.evidence} | {e["callee"] for e in incident.evidence}
        affected_edges = {(e["caller"], e["callee"]) for e in incident.evidence}
        dependencies = sorted({e["edge"] for e in incident.evidence})

        deployment_lookback = timedelta(minutes=60)
        deployment_rows = db.execute(
            select(Deployment).where(
                Deployment.workspace_id == workspace.id,
                Deployment.service_name.in_(affected_services | {incident.primary_service}),
                Deployment.deployed_at >= incident.started_at - deployment_lookback,
                Deployment.deployed_at <= incident.started_at,
            )
        ).scalars().all()
        deployments_payload = [
            {
                "service_name": d.service_name,
                "version": d.version,
                "deployed_at": d.deployed_at.isoformat(),
                "minutes_before_incident": round((incident.started_at - d.deployed_at).total_seconds() / 60, 1),
            }
            for d in deployment_rows
        ]

        request = DiagnosisRequest(
            workspace_id=str(workspace.id),
            incident_id=str(incident.id),
            incident_title=incident.title,
            primary_service=incident.primary_service,
            severity=incident.severity,
            evidence=[
                EvidenceItem(edge=e["edge"], metric=e["metric"], observed=e["observed"], baseline=e["baseline"], zscore=e["zscore"])
                for e in incident.evidence
            ],
            dependencies=dependencies,
            deployments=deployments_payload,
        )

        try:
            result = call_reasoning_service(workspace, request)
        except (ReasoningNotConfigured, ReasoningServiceError) as exc:
            logger.warning("reasoning_service_unavailable", extra={"incident_id": incident_id, "error": str(exc)})
            db.add(Event(incident_id=incident.id, kind="diagnosis_failed", message=str(exc)))
            incident.status = "open"
            db.commit()
            return
        except Exception as exc:  # noqa: BLE001 -- any other failure still lands on the incident timeline
            logger.exception("reasoning_service_failed")
            db.add(Event(incident_id=incident.id, kind="diagnosis_failed", message=str(exc)))
            incident.status = "open"
            db.commit()
            return

        # Reuse the incident's own simulation (computed independently by
        # run_incident_simulation) rather than recomputing it here. Falls
        # back to computing it fresh only if that task hasn't landed yet
        # -- Celery doesn't guarantee ordering between the two .delay()
        # calls in scan_for_anomalies.
        simulation = incident.simulation or simulate_incident_resolution(
            db, workspace.id, incident.primary_service, affected_edges
        )

        db.add(ReasoningResult(
            incident_id=incident.id,
            provider_tier=workspace.reasoning_provider_label,
            hypothesis=result.hypothesis,
            confidence=result.confidence,
            proposed_changes=result.proposed_changes,
            reasoning_trace=result.reasoning,
            cited_documents=result.cited_documents,
            simulation=simulation,
        ))
        db.add(Event(incident_id=incident.id, kind="diagnosis_complete", message=f"Hypothesis generated (confidence {result.confidence:.2f})."))
        incident.status = "open"  # stays open pending human review/approval; never auto-applied
        db.commit()


@celery_app.task(name="app.workers.tasks.seed_demo_workspace")
def seed_demo_workspace() -> None:
    """
    Keeps one public-facing demo workspace looking alive -- real traffic
    through the real ingestion pipeline (ingest_spans_batch above, the
    exact same path a real OTel collector hits), not hand-crafted fake
    dashboard data. Immediately a no-op on every deployment that hasn't
    set GHOST_DEMO_WORKSPACE_ID.

    Runs on a deterministic, stateless 10-minute cycle based on wall-
    clock time (no stored "last spike" needed, so this stays correct
    even across worker restarts or multiple worker processes): 7
    minutes of healthy traffic, then a 3-minute latency spike on
    checkout->redis, then back to healthy -- so a visitor at any given
    moment has a real chance of seeing either the calm state or an
    actual incident with real evidence, not always the same frozen
    screenshot.
    """
    settings = get_settings()
    if not settings.ghost_demo_workspace_id:
        return
    workspace_id = uuid.UUID(settings.ghost_demo_workspace_id)

    cycle_seconds = 600
    spike_seconds = 180
    in_spike = demo_cycle_is_spiking(datetime.now(timezone.utc), cycle_seconds, spike_seconds)

    spans = []
    now_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)

    def add_trace(chain: list[str], duration_ms: float, is_error: bool = False):
        trace_id = uuid.uuid4().hex
        span_ids = [uuid.uuid4().hex[:16] for _ in chain]
        for i, service in enumerate(chain):
            parent_id = span_ids[i - 1] if i > 0 else None
            spans.append({
                "id": str(uuid.uuid4()), "workspace_id": str(workspace_id),
                "trace_id": trace_id, "span_id": span_ids[i], "parent_span_id": parent_id,
                "service_name": service, "span_name": "call", "kind": "CLIENT",
                "started_at_unix_ns": now_ns, "duration_ms": duration_ms,
                "status_code": "ERROR" if (is_error and i == len(chain) - 1) else "OK",
                "attributes": {},
            })

    for _ in range(3):
        add_trace(["gateway", "checkout", "redis"], 220.0 if in_spike else 22.0, is_error=in_spike)
        add_trace(["gateway", "payments", "redis"], 20.0)
        add_trace(["gateway", "inventory", "postgres"], 18.0)

    with SyncSessionLocal() as db:
        rows = [
            Span(
                id=uuid.UUID(s["id"]), workspace_id=uuid.UUID(s["workspace_id"]),
                trace_id=s["trace_id"], span_id=s["span_id"], parent_span_id=s["parent_span_id"],
                service_name=s["service_name"], span_name=s["span_name"], kind=s["kind"],
                started_at=_ns_to_dt(s["started_at_unix_ns"]), duration_ms=s["duration_ms"],
                status_code=s["status_code"], attributes=s["attributes"],
            )
            for s in spans
        ]
        db.add_all(rows)
        db.commit()
    # Deliberately not ingest_spans_batch -- that enqueues
    # update_graph_and_baselines via .delay(), and the very next line
    # here (refresh_reference_baselines) needs the graph actually
    # updated first, not queued for some unpredictable later time.
    # Racing against Celery's own queue timing, inside a task that's
    # itself scheduled on that same queue, is exactly the kind of bug
    # that looks fine in isolation and then silently never promotes a
    # reference in production. Calling the graph update directly, once,
    # keeps this run fully synchronous and avoids double-processing the
    # same spans through both the async and sync paths.
    update_graph_and_baselines(str(workspace_id), spans)

    # Reference baselines refreshed every run (not left to the hourly
    # schedule) so a freshly deployed demo doesn't sit for an hour with
    # no "normal" established yet, before anomaly detection can fire at
    # all.
    # Only promote reference baselines during the healthy phase --
    # doing this during the spike itself would immediately fold the
    # elevated "current" latency into "reference," erasing the exact
    # deviation scan_for_anomalies needs to see. Same principle as
    # never letting a live incident's abnormal state get baked in as
    # normal, applied to the seeder's own synthetic anomaly.
    if not in_spike:
        with SyncSessionLocal() as db:
            refresh_reference_baselines(db, workspace_id)

    scan_for_anomalies()

    # Auto-resolve once back in the healthy phase, past a short grace
    # period -- otherwise incidents from every previous spike cycle
    # just pile up forever instead of demonstrating the full lifecycle
    # (open -> evidenced -> resolved).
    if not in_spike:
        with SyncSessionLocal() as db:
            open_incidents = db.execute(
                select(Incident).where(
                    Incident.workspace_id == workspace_id,
                    Incident.status.in_(["open", "diagnosing"]),
                    Incident.started_at < datetime.now(timezone.utc) - timedelta(seconds=30),
                )
            ).scalars().all()
            for incident in open_incidents:
                incident.status = "resolved"
                incident.resolved_at = datetime.now(timezone.utc)
                db.add(Event(incident_id=incident.id, kind="resolved", message="Auto-resolved by demo seeder."))
            db.commit()