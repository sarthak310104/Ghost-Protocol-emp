"""
Behavioral baselines are maintained incrementally, one span at a time, so
we never need to re-scan history to answer "is this edge behaving
normally right now." Three separate online estimators are combined per
edge:

1. EWMA of latency  -> `baseline_latency_ms_p50` (a fast-moving "typical
   latency" proxy, not a certified percentile).
2. A streaming quantile estimator (stochastic gradient descent on the
   pinball loss, step scaled by distance-to-current-estimate) tracking
   the ~99th percentile -> `baseline_latency_ms_p99`. This is a common,
   lightweight approximation for streaming systems that can't afford to
   keep a full histogram/t-digest per edge; it trades a little precision
   for O(1) memory and update cost.
3. Welford's online algorithm for running mean/variance of latency,
   which is what anomaly z-scoring is actually computed against (more
   stable than differencing the two quantile estimates above).

None of this claims exact-percentile accuracy -- it's explicitly a
drift-detection baseline, not a billing-grade metrics pipeline.
"""
from dataclasses import dataclass

from app.core.config import get_settings

settings = get_settings()

_P99_LEARNING_RATE = 0.05
_P99_TARGET_QUANTILE = 0.99


@dataclass
class EdgeObservation:
    duration_ms: float
    is_error: bool


def update_edge_baseline(edge, observation: EdgeObservation) -> None:
    """Mutates a ServiceEdge ORM instance in place with one new observation (the fast/current side only)."""
    alpha = settings.baseline_ewma_alpha
    x = observation.duration_ms

    if edge.sample_count == 0:
        edge.current_latency_ms_p50 = x
        edge.current_latency_ms_p99 = x
        edge.current_latency_variance = 0.0
        edge.current_error_rate = 1.0 if observation.is_error else 0.0
    else:
        # 1. EWMA mean
        edge.current_latency_ms_p50 = (1 - alpha) * edge.current_latency_ms_p50 + alpha * x

        # 2. Streaming p99 (SGD on pinball loss, step scaled by distance so
        #    it adapts to the edge's own latency scale rather than a fixed
        #    millisecond step).
        direction = 1.0 if x > edge.current_latency_ms_p99 else -1.0
        step_target = _P99_TARGET_QUANTILE if direction > 0 else (1 - _P99_TARGET_QUANTILE)
        edge.current_latency_ms_p99 += (
            _P99_LEARNING_RATE * step_target * direction * abs(x - edge.current_latency_ms_p99)
        )

        # 3. Welford update for mean/variance of the *current* window.
        n = edge.sample_count + 1
        delta = x - edge.current_latency_ms_p50
        edge.current_latency_variance = (
            (edge.sample_count * edge.current_latency_variance) + delta * delta * (edge.sample_count / n)
        ) / n

        # EWMA error rate
        edge.current_error_rate = (1 - alpha) * edge.current_error_rate + alpha * (1.0 if observation.is_error else 0.0)

    edge.sample_count += 1


def zscore_against_reference(edge) -> float:
    """
    How many standard deviations the edge's *current* latency is from its
    *reference* (normal) latency. Returns 0.0 until a reference snapshot
    exists (see app/graph/reference.py) -- an edge needs a "normal" to be
    compared against before it can be judged anomalous.
    """
    if edge.reference_updated_at is None or edge.reference_latency_stddev < 1e-6:
        return 0.0
    return (edge.current_latency_ms_p99 - edge.reference_latency_ms) / edge.reference_latency_stddev
