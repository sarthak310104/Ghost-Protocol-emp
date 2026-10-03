from datetime import datetime

from app.evidence.schema import DeploymentMarker, EvidencePackage, Observation, TimelineEntry


def assemble_evidence_package(
    incident_id: str,
    primary_service: str,
    raw_evidence: list[dict],
    events: list,       # ORM Event rows or objects with .kind/.message/.occurred_at
    deployments: list,  # ORM Deployment rows, already filtered to the relevant window
    incident_started_at: datetime,
    simulation_results: list[dict],
    config_drift: list[dict] | None = None,  # already-serialized ConfigDrift.to_dict() entries
) -> EvidencePackage:
    """
    Pure assembly -- no DB access here, so the exact same function builds
    the evidence package whether called from a sync Celery task or an
    async FastAPI route. Callers are responsible for fetching and
    filtering `events`/`deployments` first, and for computing
    `config_drift` first (see app/deployments/drift.py -- its own
    lookback logic is deliberately not the same recency window
    `deployments` uses here, so it isn't something this function could
    derive from `deployments` itself).
    """
    observations = [
        Observation(
            metric=f"{e['edge']} {e['metric']}",
            current=e["observed"],
            baseline=e.get("baseline"),
        )
        for e in raw_evidence
    ]

    dependencies = sorted({e["edge"] for e in raw_evidence})

    timeline = [
        TimelineEntry(kind=ev.kind, message=ev.message, occurred_at=ev.occurred_at.isoformat())
        for ev in events
    ]

    deployment_markers = [
        DeploymentMarker(
            service_name=d.service_name,
            version=d.version,
            deployed_at=d.deployed_at.isoformat(),
            minutes_before_incident=(incident_started_at - d.deployed_at).total_seconds() / 60,
        )
        for d in deployments
        if d.deployed_at <= incident_started_at
    ]

    return EvidencePackage(
        incident_id=incident_id,
        service=primary_service,
        observations=observations,
        dependencies=dependencies,
        timeline=timeline,
        deployments=deployment_markers,
        config_drift=config_drift or [],
        simulation_results=simulation_results,
    )