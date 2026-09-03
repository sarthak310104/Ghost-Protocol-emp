import datetime

import pytest

from app.bottleneck.baseline import risk_zscore_against_reference, update_risk_baseline


def test_first_scan_sets_current_risk_score_directly(node_factory):
    node = node_factory()
    update_risk_baseline(node, risk_score=0.5)

    assert node.current_risk_score == 0.5
    assert node.risk_score_variance == 0.0
    assert node.risk_scan_count == 1


def test_repeated_identical_scans_converge_variance_to_zero(node_factory):
    node = node_factory()
    for _ in range(10):
        update_risk_baseline(node, risk_score=0.4)

    assert node.current_risk_score == pytest.approx(0.4)
    assert node.risk_score_variance < 1e-6


def test_zscore_is_zero_without_a_reference(node_factory):
    node = node_factory(reference_risk_updated_at=None)
    assert risk_zscore_against_reference(node) == 0.0


def test_zscore_is_zero_for_a_stable_service_with_reference_set_to_current(node_factory):
    # This is exactly the "quiet" case verified against the real
    # deployment: a service whose current risk matches its own
    # established normal should score 0, not some fixed baseline.
    node = node_factory(
        current_risk_score=0.567,
        reference_risk_score=0.567,
        reference_risk_stddev=1e-3,
        reference_risk_updated_at=datetime.datetime.now(datetime.timezone.utc),
    )
    assert risk_zscore_against_reference(node) == pytest.approx(0.0)


def test_a_real_structural_change_produces_a_large_zscore(node_factory):
    # Same shape as the live test: redis's risk moved from 0.567 to
    # 0.600 after a new caller was added, against a near-zero reference
    # stddev (a previously very stable service) -- that should read as
    # a large deviation, not get lost in the noise.
    node = node_factory(
        current_risk_score=0.600,
        reference_risk_score=0.567,
        reference_risk_stddev=0.001,
        reference_risk_updated_at=datetime.datetime.now(datetime.timezone.utc),
    )
    z = risk_zscore_against_reference(node)
    assert z > 3.0  # comfortably past the platform's own anomaly threshold


def test_two_services_with_the_same_absolute_risk_score_can_have_different_zscores(node_factory):
    # The entire point of per-service baselining: identical risk_score
    # values are not necessarily equally "unusual" -- it depends on
    # what's normal for each specific service.
    stable_service = node_factory(
        current_risk_score=0.5,
        reference_risk_score=0.5,
        reference_risk_stddev=0.01,
        reference_risk_updated_at=datetime.datetime.now(datetime.timezone.utc),
    )
    spiking_service = node_factory(
        current_risk_score=0.5,
        reference_risk_score=0.2,
        reference_risk_stddev=0.01,
        reference_risk_updated_at=datetime.datetime.now(datetime.timezone.utc),
    )
    assert risk_zscore_against_reference(stable_service) == pytest.approx(0.0)
    assert risk_zscore_against_reference(spiking_service) > 20.0