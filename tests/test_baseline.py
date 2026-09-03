import datetime

import pytest

from app.graph.baseline import EdgeObservation, update_edge_baseline, zscore_against_reference


def test_first_observation_sets_values_directly(edge_factory):
    edge = edge_factory()
    update_edge_baseline(edge, EdgeObservation(duration_ms=100.0, is_error=False))

    assert edge.current_latency_ms_p50 == 100.0
    assert edge.current_latency_ms_p99 == 100.0
    assert edge.current_latency_variance == 0.0
    assert edge.sample_count == 1


def test_ewma_moves_toward_new_observations_but_doesnt_jump_straight_to_them(edge_factory):
    edge = edge_factory()
    update_edge_baseline(edge, EdgeObservation(duration_ms=100.0, is_error=False))
    update_edge_baseline(edge, EdgeObservation(duration_ms=200.0, is_error=False))

    # alpha=0.2 by default: p50 should move up from 100 toward 200, but
    # land well short of 200 after a single observation -- if it jumped
    # straight to the new value this wouldn't be an EWMA at all.
    assert 100.0 < edge.current_latency_ms_p50 < 200.0
    assert edge.current_latency_ms_p50 == pytest.approx(0.8 * 100.0 + 0.2 * 200.0)


def test_stable_latency_keeps_variance_near_zero(edge_factory):
    edge = edge_factory()
    for _ in range(20):
        update_edge_baseline(edge, EdgeObservation(duration_ms=50.0, is_error=False))

    assert edge.current_latency_variance < 1.0
    assert edge.sample_count == 20


def test_volatile_latency_produces_meaningfully_higher_variance_than_stable(edge_factory):
    stable = edge_factory()
    volatile = edge_factory()

    for _ in range(20):
        update_edge_baseline(stable, EdgeObservation(duration_ms=50.0, is_error=False))

    values = [10.0, 90.0, 20.0, 80.0, 15.0, 95.0, 5.0, 100.0] * 3
    for v in values:
        update_edge_baseline(volatile, EdgeObservation(duration_ms=v, is_error=False))

    assert volatile.current_latency_variance > stable.current_latency_variance


def test_error_rate_ewma_rises_toward_one_under_sustained_errors(edge_factory):
    edge = edge_factory()
    for _ in range(30):
        update_edge_baseline(edge, EdgeObservation(duration_ms=50.0, is_error=True))

    # EWMA never fully reaches 1.0, but should get close after enough
    # consistent error observations.
    assert edge.current_error_rate > 0.95


def test_zscore_is_zero_without_a_reference_baseline(edge_factory):
    edge = edge_factory(reference_updated_at=None)
    assert zscore_against_reference(edge) == 0.0


def test_zscore_is_zero_when_reference_stddev_is_effectively_zero(edge_factory):
    edge = edge_factory(
        reference_updated_at=datetime.datetime.now(datetime.timezone.utc),
        reference_latency_stddev=0.0,
        reference_latency_ms=50.0,
        current_latency_ms_p99=500.0,
    )
    # a real anomaly (10x latency) must not divide by ~zero and blow up
    # into a nonsensical value -- this is the guard that prevents that
    assert zscore_against_reference(edge) == 0.0


def test_zscore_reflects_real_deviation_from_reference(edge_factory):
    edge = edge_factory(
        reference_updated_at=datetime.datetime.now(datetime.timezone.utc),
        reference_latency_ms=100.0,
        reference_latency_stddev=10.0,
        current_latency_ms_p99=150.0,
    )
    # (150 - 100) / 10 = 5.0 standard deviations above normal
    assert zscore_against_reference(edge) == pytest.approx(5.0)