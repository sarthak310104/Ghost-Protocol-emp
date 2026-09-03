import datetime

from app.incident.detect import detect_edge_anomalies


def test_edge_without_reference_baseline_never_flags(edge_factory):
    edge = edge_factory(reference_updated_at=None, current_latency_ms_p99=99999.0)
    assert detect_edge_anomalies([edge]) == []


def test_edge_within_normal_range_does_not_flag(edge_factory):
    edge = edge_factory(
        reference_updated_at=datetime.datetime.now(datetime.timezone.utc),
        reference_latency_ms=100.0,
        reference_latency_stddev=10.0,
        current_latency_ms_p99=105.0,  # half a stddev above normal
        current_error_rate=0.01,
        reference_error_rate=0.01,
    )
    assert detect_edge_anomalies([edge]) == []


def test_latency_spike_past_zscore_threshold_flags_a_latency_anomaly(edge_factory):
    edge = edge_factory(
        caller="checkout", callee="redis",
        reference_updated_at=datetime.datetime.now(datetime.timezone.utc),
        reference_latency_ms=100.0,
        reference_latency_stddev=10.0,
        current_latency_ms_p99=500.0,  # 40 stddev above normal, way past threshold
        current_error_rate=0.0,
        reference_error_rate=0.0,
    )
    anomalies = detect_edge_anomalies([edge])
    latency_anomalies = [a for a in anomalies if a.metric == "latency_p99_ms"]
    assert len(latency_anomalies) == 1
    assert latency_anomalies[0].edge == "checkout->redis"


def test_small_error_rate_jump_does_not_flag(edge_factory):
    edge = edge_factory(
        reference_updated_at=datetime.datetime.now(datetime.timezone.utc),
        reference_latency_ms=100.0, reference_latency_stddev=10.0, current_latency_ms_p99=100.0,
        current_error_rate=0.05, reference_error_rate=0.02,  # 3-point jump, under the 10-point threshold
    )
    error_anomalies = [a for a in detect_edge_anomalies([edge]) if a.metric == "error_rate"]
    assert error_anomalies == []


def test_large_error_rate_jump_flags_an_error_rate_anomaly(edge_factory):
    edge = edge_factory(
        reference_updated_at=datetime.datetime.now(datetime.timezone.utc),
        reference_latency_ms=100.0, reference_latency_stddev=10.0, current_latency_ms_p99=100.0,
        current_error_rate=0.20, reference_error_rate=0.01,  # 19-point jump
    )
    error_anomalies = [a for a in detect_edge_anomalies([edge]) if a.metric == "error_rate"]
    assert len(error_anomalies) == 1


def test_an_edge_can_flag_both_latency_and_error_rate_at_once(edge_factory):
    edge = edge_factory(
        reference_updated_at=datetime.datetime.now(datetime.timezone.utc),
        reference_latency_ms=100.0, reference_latency_stddev=10.0, current_latency_ms_p99=500.0,
        current_error_rate=0.30, reference_error_rate=0.01,
    )
    anomalies = detect_edge_anomalies([edge])
    assert {a.metric for a in anomalies} == {"latency_p99_ms", "error_rate"}