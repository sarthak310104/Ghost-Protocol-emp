import pytest

from app.deployments.retrospective import _compute_comparison, _compute_stat


def test_stat_is_none_for_empty_rows():
    assert _compute_stat("before", []) is None


def test_stat_computes_mean_and_sample_count():
    rows = [(100.0, "OK"), (200.0, "OK"), (300.0, "OK")]
    stat = _compute_stat("before", rows)
    assert stat.sample_count == 3
    assert stat.mean_latency_ms == pytest.approx(200.0)


def test_stat_computes_error_rate():
    rows = [(100.0, "OK"), (100.0, "OK"), (100.0, "ERROR"), (100.0, "OK")]
    stat = _compute_stat("after", rows)
    assert stat.error_rate == pytest.approx(0.25)


def test_comparison_is_none_when_either_window_has_no_data():
    before = _compute_stat("before", [(100.0, "OK")] * 40)
    assert _compute_comparison(before, None) == (None, (
        "No spans on this edge in one or both windows -- nothing to compare. "
        "A config change older than the telemetry retention window has no "
        "surviving \"before\" data."
    ))
    assert _compute_comparison(None, before) == (None, (
        "No spans on this edge in one or both windows -- nothing to compare. "
        "A config change older than the telemetry retention window has no "
        "surviving \"before\" data."
    ))


def test_comparison_is_none_when_a_window_is_under_the_minimum_sample_size():
    before = _compute_stat("before", [(100.0, "OK")] * 40)
    after = _compute_stat("after", [(50.0, "OK")] * 5)  # below the documented floor of 30
    comparison, note = _compute_comparison(before, after)
    assert comparison is None
    assert "fewer than 30 samples" in note


def test_comparison_computes_a_real_difference_with_enough_samples_each():
    # Same shape as the live cohort-analysis test: ~40 samples before
    # at one latency, ~35 after at a meaningfully lower one -- as if a
    # config change actually helped.
    before = _compute_stat("before", [(230.0, "OK")] * 40)
    after = _compute_stat("after", [(95.0, "OK")] * 35)
    comparison, note = _compute_comparison(before, after)

    assert note is None
    assert comparison is not None
    assert comparison.difference_pct < -50  # meaningfully lower
    assert comparison.method == "two_sample_z_approximation_before_after"
    # the CI should bracket the point estimate
    assert comparison.ci_95_low_pct <= comparison.difference_pct <= comparison.ci_95_high_pct


def test_identical_before_and_after_produce_roughly_zero_difference():
    before = _compute_stat("before", [(100.0, "OK")] * 40)
    after = _compute_stat("after", [(100.0, "OK")] * 40)
    comparison, note = _compute_comparison(before, after)
    assert note is None
    assert comparison is not None
    assert comparison.difference_pct == pytest.approx(0.0)


def test_comparison_is_none_when_before_mean_is_zero():
    before = _compute_stat("before", [(0.0, "OK")] * 40)
    after = _compute_stat("after", [(50.0, "OK")] * 40)
    comparison, note = _compute_comparison(before, after)
    assert comparison is None
    assert "zero mean latency" in note