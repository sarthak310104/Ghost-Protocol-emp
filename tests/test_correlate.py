from app.incident.correlate import _group_connected
from app.incident.detect import Anomaly


def make_anomaly(caller, callee, metric="latency_p99_ms") -> Anomaly:
    return Anomaly(
        edge=f"{caller}->{callee}", caller=caller, callee=callee, metric=metric,
        observed=100.0, baseline=10.0, zscore=5.0, detected_at="2026-01-01T00:00:00Z",
    )


def test_single_anomaly_forms_its_own_group():
    groups = _group_connected([make_anomaly("checkout", "redis")])
    assert len(groups) == 1
    assert len(groups[0]) == 1


def test_two_anomalies_sharing_a_service_merge_into_one_group():
    # cache miss (checkout->redis) triggering DB load (checkout->postgres)
    # -- both touch "checkout", so this should be one incident, not two.
    anomalies = [make_anomaly("checkout", "redis"), make_anomaly("checkout", "postgres")]
    groups = _group_connected(anomalies)
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_a_three_hop_chain_all_merges_into_one_group():
    # cache miss -> DB load -> API latency: a chain where each pair
    # shares a service with its neighbor, but the two ends share
    # nothing directly. Union-find should still merge all three.
    anomalies = [
        make_anomaly("checkout", "redis"),
        make_anomaly("redis", "postgres"),
        make_anomaly("postgres", "storage_backend"),
    ]
    groups = _group_connected(anomalies)
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_unrelated_anomalies_on_disjoint_services_stay_separate():
    anomalies = [
        make_anomaly("checkout", "redis"),
        make_anomaly("shipping", "postgres"),
    ]
    groups = _group_connected(anomalies)
    assert len(groups) == 2


def test_no_anomalies_returns_no_groups():
    assert _group_connected([]) == []