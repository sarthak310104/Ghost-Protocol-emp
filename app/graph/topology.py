"""
Edge derivation from span topology. Deliberately batch-local: we only
link a span to its parent's service if the parent span arrived in the
same ingestion batch. In practice, OTel collectors batch-export spans
for a whole trace close together, so this covers the overwhelming
majority of edges. A cross-batch parent lookup (querying `spans` by
span_id) is a reasonable follow-up if this ever misses edges in
production traffic patterns -- noted here rather than silently assumed
away.
"""
from dataclasses import dataclass


@dataclass
class DerivedEdge:
    caller: str
    callee: str
    duration_ms: float
    is_error: bool


def derive_edges(spans: list[dict]) -> list[DerivedEdge]:
    span_id_to_service = {s["span_id"]: s["service_name"] for s in spans}

    edges: list[DerivedEdge] = []
    for span in spans:
        parent_id = span.get("parent_span_id")
        if not parent_id:
            continue  # root span of a trace -- no caller within this system
        parent_service = span_id_to_service.get(parent_id)
        if not parent_service or parent_service == span["service_name"]:
            continue  # parent not in this batch, or same-service internal span
        edges.append(DerivedEdge(
            caller=parent_service,
            callee=span["service_name"],
            duration_ms=span["duration_ms"],
            is_error=span["status_code"] == "ERROR",
        ))
    return edges
