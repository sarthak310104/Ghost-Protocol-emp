"""
Bottleneck engine: finds structurally risky points in the behavioral
graph *before* they cause an incident. This is intentionally separate
from anomaly-based incident detection (app/incident/detect.py) -- a
service can be a structural bottleneck (high fan-in, on every critical
path) while its current metrics still look perfectly healthy.

The risk score is a transparent, documented heuristic, not a learned
model: fan-in share + critical-path membership + current error-rate
baseline, weighted and normalized to [0, 1]. Every factor is returned
alongside the score so the dashboard can show *why* a node is flagged,
matching the "explain everything" principle in the original design.
"""
from collections import defaultdict
from dataclasses import dataclass, field

from app.models.graph import ServiceEdge


@dataclass
class NodeRisk:
    service: str
    fan_in: int
    fan_out: int
    critical_path_membership: float  # fraction of root->leaf paths this node sits on
    error_rate_baseline: float
    risk_score: float
    contributing_edges: list[str] = field(default_factory=list)


def _build_adjacency(edges: list[ServiceEdge]) -> tuple[dict[str, list[ServiceEdge]], dict[str, int], dict[str, int]]:
    out_edges: dict[str, list[ServiceEdge]] = defaultdict(list)
    fan_in: dict[str, int] = defaultdict(int)
    fan_out: dict[str, int] = defaultdict(int)

    services = set()
    for e in edges:
        out_edges[e.caller].append(e)
        fan_out[e.caller] += 1
        fan_in[e.callee] += 1
        services.add(e.caller)
        services.add(e.callee)

    for s in services:
        fan_in.setdefault(s, 0)
        fan_out.setdefault(s, 0)

    return out_edges, fan_in, fan_out


def _enumerate_root_to_leaf_paths(out_edges: dict[str, list[ServiceEdge]], all_services: set[str]) -> list[list[str]]:
    """
    Enumerates simple root->leaf paths (roots = no incoming edges). Guards
    against cycles (retries, circular calls) by refusing to revisit a node
    within the same path -- this makes "critical path" well-defined even
    on a graph that isn't a strict DAG.
    """
    callees = {e.callee for edges in out_edges.values() for e in edges}
    roots = [s for s in all_services if s not in callees] or list(all_services)[:1]

    paths: list[list[str]] = []

    def dfs(node: str, path: list[str]):
        path = path + [node]
        children = [e.callee for e in out_edges.get(node, []) if e.callee not in path]
        if not children:
            paths.append(path)
            return
        for child in children:
            dfs(child, path)

    for root in roots:
        dfs(root, [])
    return paths


def compute_bottlenecks(edges: list[ServiceEdge]) -> list[NodeRisk]:
    if not edges:
        return []

    out_edges, fan_in, fan_out = _build_adjacency(edges)
    all_services = set(fan_in) | set(fan_out)

    paths = _enumerate_root_to_leaf_paths(out_edges, all_services)
    path_count = max(len(paths), 1)

    membership_count: dict[str, int] = defaultdict(int)
    for path in paths:
        for node in set(path):
            membership_count[node] += 1

    error_rate_by_service: dict[str, float] = {}
    edges_by_service: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        # a service's own "error baseline" = worst inbound edge error rate
        current = error_rate_by_service.get(e.callee, 0.0)
        # Use the edge's live "current" error rate for risk scoring --
        # bottleneck risk should reflect what's happening right now, not
        # the slow-moving "reference/normal" baseline anomaly detection
        # compares against.
        error_rate_by_service[e.callee] = max(current, e.current_error_rate)
        edges_by_service[e.callee].append(f"{e.caller}->{e.callee}")

    max_fan_in = max(fan_in.values(), default=1) or 1

    results: list[NodeRisk] = []
    for service in all_services:
        fan_in_norm = fan_in[service] / max_fan_in
        critical_path_membership = membership_count.get(service, 0) / path_count
        error_rate = error_rate_by_service.get(service, 0.0)

        risk_score = (0.3 * fan_in_norm) + (0.4 * critical_path_membership) + (0.3 * min(error_rate * 10, 1.0))

        results.append(NodeRisk(
            service=service,
            fan_in=fan_in[service],
            fan_out=fan_out[service],
            critical_path_membership=round(critical_path_membership, 3),
            error_rate_baseline=round(error_rate, 4),
            risk_score=round(risk_score, 3),
            contributing_edges=edges_by_service.get(service, []),
        ))

    return sorted(results, key=lambda r: r.risk_score, reverse=True)