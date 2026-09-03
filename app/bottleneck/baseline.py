"""
A service's structural risk_score gets the same current/reference
baseline treatment as an edge's latency (see app/graph/baseline.py) --
but updated once per bottleneck scan (every 5 minutes, see
run_bottleneck_scan) rather than per-span, since risk_score is a
graph-structural computation that needs the whole graph snapshot, not
a per-request measurement. Same underlying math either way: an EWMA of
the current value, and Welford's algorithm for that value's own
running variance, which is what "how unusual is this compared to what
THIS service normally looks like" is scored against.
"""
from app.core.config import get_settings

settings = get_settings()


def update_risk_baseline(node, risk_score: float) -> None:
    """Mutates a ServiceNode ORM instance in place with one new risk_score observation."""
    alpha = settings.baseline_ewma_alpha

    if node.risk_scan_count == 0:
        node.current_risk_score = risk_score
        node.risk_score_variance = 0.0
    else:
        node.current_risk_score = (1 - alpha) * node.current_risk_score + alpha * risk_score

        n = node.risk_scan_count + 1
        delta = risk_score - node.current_risk_score
        node.risk_score_variance = (
            (node.risk_scan_count * node.risk_score_variance) + delta * delta * (node.risk_scan_count / n)
        ) / n

    node.risk_scan_count += 1


def risk_zscore_against_reference(node) -> float:
    """
    How many standard deviations this service's *current* risk score is
    from its *own reference* (normal) risk score. Returns 0.0 until a
    reference snapshot exists -- a service needs an established "normal"
    before "unusually risky for it" is a meaningful question, same as
    edge anomaly detection needs a latency reference first.
    """
    if node.reference_risk_updated_at is None or node.reference_risk_stddev < 1e-6:
        return 0.0
    return (node.current_risk_score - node.reference_risk_score) / node.reference_risk_stddev