from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import get_settings
from app.graph.baseline import zscore_against_reference
from app.models.graph import ServiceEdge

settings = get_settings()


@dataclass
class Anomaly:
    edge: str  # "caller->callee"
    caller: str
    callee: str
    metric: str
    observed: float
    baseline: float
    zscore: float
    detected_at: str

    def to_evidence_dict(self) -> dict:
        return {
            "edge": self.edge,
            "caller": self.caller,
            "callee": self.callee,
            "metric": self.metric,
            "observed": round(self.observed, 3),
            "baseline": round(self.baseline, 3),
            "zscore": round(self.zscore, 2),
            "detected_at": self.detected_at,
        }


def detect_edge_anomalies(edges: list[ServiceEdge]) -> list[Anomaly]:
    """Pure function: given edges (with current + reference baselines already loaded), return anomalies."""
    now = datetime.now(timezone.utc).isoformat()
    anomalies: list[Anomaly] = []

    for edge in edges:
        if edge.reference_updated_at is None:
            continue  # no "normal" established yet for this edge

        z = zscore_against_reference(edge)
        if abs(z) >= settings.anomaly_zscore_threshold:
            anomalies.append(Anomaly(
                edge=f"{edge.caller}->{edge.callee}",
                caller=edge.caller,
                callee=edge.callee,
                metric="latency_p99_ms",
                observed=edge.current_latency_ms_p99,
                baseline=edge.reference_latency_ms,
                zscore=z,
                detected_at=now,
            ))

        # Error rate: absolute-jump heuristic rather than z-score, since
        # error rate near zero makes z-scores unstable (tiny stddev).
        error_jump = edge.current_error_rate - edge.reference_error_rate
        if error_jump >= 0.1:  # 10-point jump in error rate
            anomalies.append(Anomaly(
                edge=f"{edge.caller}->{edge.callee}",
                caller=edge.caller,
                callee=edge.callee,
                metric="error_rate",
                observed=edge.current_error_rate,
                baseline=edge.reference_error_rate,
                zscore=error_jump / 0.1,  # scaled so downstream severity logic stays consistent
                detected_at=now,
            ))

    return anomalies
