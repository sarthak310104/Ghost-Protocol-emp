"""
Ghost Protocol's most important output. Everything the behavioral,
incident, and simulation engines produce for one incident gets
assembled here into a single structured package -- this is what powers
the dashboard, the incident API, reports, and (optionally) an external
reasoning system. Nothing in this file makes a causal claim; it's a
transcription of what was observed and what the simulation projected.
"""
from dataclasses import dataclass, field


@dataclass
class Observation:
    metric: str
    current: float
    baseline: float | None = None  # None for a metric with no established reference yet

    def to_dict(self) -> dict:
        d = {"metric": self.metric, "current": self.current}
        if self.baseline is not None:
            d["baseline"] = self.baseline
        return d


@dataclass
class DeploymentMarker:
    service_name: str
    version: str
    deployed_at: str  # ISO8601
    minutes_before_incident: float

    def to_dict(self) -> dict:
        return {
            "service_name": self.service_name,
            "version": self.version,
            "deployed_at": self.deployed_at,
            "minutes_before_incident": round(self.minutes_before_incident, 1),
        }


@dataclass
class TimelineEntry:
    kind: str
    message: str
    occurred_at: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "occurred_at": self.occurred_at}


@dataclass
class EvidencePackage:
    incident_id: str
    service: str
    observations: list[Observation]
    dependencies: list[str]  # ["checkout -> redis", "checkout -> postgres"]
    timeline: list[TimelineEntry] = field(default_factory=list)
    deployments: list[DeploymentMarker] = field(default_factory=list)
    simulation_results: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "incident": {"id": self.incident_id, "service": self.service},
            "observations": [o.to_dict() for o in self.observations],
            "dependencies": self.dependencies,
            "timeline": [t.to_dict() for t in self.timeline],
            "deployments": [d.to_dict() for d in self.deployments],
            "simulation_results": self.simulation_results,
        }
