import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_workspace_from_session_or_key
from app.db.session import get_db
from app.evidence.builder import assemble_evidence_package
from app.models.deployment import Deployment
from app.models.incident import Event, Incident, ReasoningResult
from app.models.workspace import Workspace

router = APIRouter()

_DEPLOYMENT_LOOKBACK = timedelta(minutes=60)


@router.get("/v1/incidents")
async def list_incidents(
    status_filter: str | None = None,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    query = select(Incident).where(Incident.workspace_id == workspace.id).order_by(Incident.started_at.desc())
    if status_filter:
        query = query.where(Incident.status == status_filter)
    incidents = (await db.execute(query.limit(100))).scalars().all()
    return [
        {
            "id": str(i.id), "title": i.title, "status": i.status, "severity": i.severity,
            "primary_service": i.primary_service, "started_at": i.started_at.isoformat(),
            "last_seen_at": i.last_seen_at.isoformat(),
            "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
        }
        for i in incidents
    ]


@router.get("/v1/incidents/{incident_id}")
async def get_incident(
    incident_id: str,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    incident = await db.get(Incident, uuid.UUID(incident_id))
    if incident is None or incident.workspace_id != workspace.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")

    events = (await db.execute(
        select(Event).where(Event.incident_id == incident.id).order_by(Event.occurred_at)
    )).scalars().all()
    results = (await db.execute(
        select(ReasoningResult).where(ReasoningResult.incident_id == incident.id).order_by(ReasoningResult.created_at.desc())
    )).scalars().all()

    return {
        "id": str(incident.id), "title": incident.title, "status": incident.status,
        "severity": incident.severity, "primary_service": incident.primary_service,
        "started_at": incident.started_at.isoformat(),
        "last_seen_at": incident.last_seen_at.isoformat(),
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        "evidence": incident.evidence,
        "timeline": [{"kind": e.kind, "message": e.message, "occurred_at": e.occurred_at.isoformat()} for e in events],
        "reasoning_results": [
            {
                "id": str(r.id), "provider_tier": r.provider_tier, "hypothesis": r.hypothesis,
                "confidence": r.confidence, "proposed_changes": r.proposed_changes,
                "reasoning_trace": r.reasoning_trace, "cited_documents": r.cited_documents,
                "simulation": r.simulation, "created_at": r.created_at.isoformat(),
            }
            for r in results
        ],
    }


@router.get("/v1/incidents/{incident_id}/evidence")
async def get_incident_evidence(
    incident_id: str,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Ghost Protocol's structured evidence output for one incident --
    observations, dependency edges, timeline, correlated deployments, and
    any simulation results so far -- assembled into the schema this
    platform is meant to produce (see README). This is what a dashboard,
    a report, or an optional external reasoning system consumes; nothing
    here asserts a cause.
    """
    incident = await db.get(Incident, uuid.UUID(incident_id))
    if incident is None or incident.workspace_id != workspace.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")

    events = (await db.execute(
        select(Event).where(Event.incident_id == incident.id).order_by(Event.occurred_at)
    )).scalars().all()

    services_in_incident = {incident.primary_service} | {
        s for e in incident.evidence for s in (e.get("caller"), e.get("callee")) if s
    }
    deployments = (await db.execute(
        select(Deployment).where(
            Deployment.workspace_id == workspace.id,
            Deployment.service_name.in_(services_in_incident),
            Deployment.deployed_at >= incident.started_at - _DEPLOYMENT_LOOKBACK,
        )
    )).scalars().all()

    # Ghost's own simulation, computed independently of any external
    # reasoning call (see run_incident_simulation) -- this is present
    # even when no reasoning service is configured at all. A
    # ReasoningResult's own simulation snapshot (if any diagnosis ran)
    # is intentionally not queried here; incident.simulation is the
    # single source of truth for this field.
    simulation_results = [incident.simulation] if incident.simulation else []

    package = assemble_evidence_package(
        incident_id=str(incident.id),
        primary_service=incident.primary_service,
        raw_evidence=incident.evidence,
        events=events,
        deployments=deployments,
        incident_started_at=incident.started_at,
        simulation_results=simulation_results,
    )
    result = package.to_dict()
    result["incident"]["last_seen_at"] = incident.last_seen_at.isoformat()
    return result


@router.post("/v1/incidents/{incident_id}/resolve")
async def resolve_incident(
    incident_id: str,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    incident = await db.get(Incident, uuid.UUID(incident_id))
    if incident is None or incident.workspace_id != workspace.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")

    incident.status = "resolved"
    incident.resolved_at = datetime.now(timezone.utc)
    db.add(Event(incident_id=incident.id, kind="resolved", message="Marked resolved by operator."))
    await db.commit()
    return {"id": incident_id, "status": "resolved"}