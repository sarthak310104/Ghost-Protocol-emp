import pytest

from app.cohort.analysis import _compute_comparison, _compute_stats


def test_rows_with_no_cohort_value_are_ignored():
    rows = [(100.0, None), (110.0, None)]
    assert _compute_stats(rows) == []


def test_groups_by_cohort_value_and_computes_sample_count():
    rows = [(100.0, "a"), (110.0, "a"), (200.0, "b")]
    stats = {s.value: s for s in _compute_stats(rows)}
    assert stats["a"].sample_count == 2
    assert stats["b"].sample_count == 1


def test_mean_latency_is_computed_correctly():
    rows = [(100.0, "a"), (200.0, "a"), (300.0, "a")]
    stats = _compute_stats(rows)
    assert stats[0].mean_latency_ms == pytest.approx(200.0)


def test_stats_are_sorted_by_sample_count_descending():
    rows = [(1.0, "small")] * 3 + [(1.0, "big")] * 10
    stats = _compute_stats(rows)
    assert [s.value for s in stats] == ["big", "small"]


def test_comparison_is_none_with_fewer_than_two_cohorts():
    rows = [(100.0, "only")] * 50
    stats = _compute_stats(rows)
    assert _compute_comparison(stats) is None


def test_comparison_is_none_when_a_cohort_is_under_the_minimum_sample_size():
    # 40 samples in one cohort, only 5 in the other -- below the
    # documented floor of 30, so no comparison should be computed even
    # though there are technically two groups.
    rows = [(100.0, "a")] * 40 + [(50.0, "b")] * 5
    stats = _compute_stats(rows)
    assert _compute_comparison(stats) is None


def test_comparison_computes_a_real_difference_with_enough_samples_each():
    # Same shape as the live canary test: ~40 samples at one latency,
    # ~35 at a meaningfully lower one.
    rows = [(230.0, "30")] * 40 + [(95.0, "300")] * 35
    stats = _compute_stats(rows)
    comparison = _compute_comparison(stats)

    assert comparison is not None
    assert comparison.baseline_cohort == "30"
    assert comparison.compared_cohort == "300"
    assert comparison.difference_pct < -50  # meaningfully lower, matches the live result's shape
    assert comparison.method == "two_sample_z_approximation"
    # the CI should bracket the point estimate
    assert comparison.ci_95_low_pct <= comparison.difference_pct <= comparison.ci_95_high_pct


def test_identical_cohorts_produce_roughly_zero_difference():
    rows = [(100.0, "a")] * 40 + [(100.0, "b")] * 40
    stats = _compute_stats(rows)
    comparison = _compute_comparison(stats)
    assert comparison is not None
    assert comparison.difference_pct == pytest.approx(0.0)