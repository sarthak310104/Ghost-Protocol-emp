"""
app/slo/budget.py's compute_slo_status is pure (no DB access), so it's
tested directly against constructed HourlyCount rows, same DB-free
pattern as the rest of the algorithmic core.
"""
import pytest

from app.slo.budget import FAST_BURN_THRESHOLD, HourlyCount, compute_slo_status


def test_no_traffic_in_window_reports_none_not_100_percent():
    status = compute_slo_status("checkout", target_percent=99.9, window_days=30, window_rollups=[], most_recent_hour=None)
    assert status.total_count == 0
    assert status.actual_percent is None
    assert status.burn_rate_1h is None
    assert status.is_fast_burning is False


def test_perfect_service_has_full_budget_remaining():
    rollups = [HourlyCount(total_count=1000, error_count=0) for _ in range(24)]
    status = compute_slo_status(
        "checkout", target_percent=99.9, window_days=30, window_rollups=rollups, most_recent_hour=rollups[-1]
    )
    assert status.actual_percent == 100.0
    assert status.error_budget_remaining_percent == 100.0
    assert status.burn_rate_1h == 0.0
    assert status.is_fast_burning is False


def test_error_budget_consumed_matches_errors_seen():
    # target 99% over the window -> allowed error rate 1% -> budget = 1% of total traffic
    rollups = [HourlyCount(total_count=1000, error_count=5)]
    status = compute_slo_status(
        "checkout", target_percent=99.0, window_days=30, window_rollups=rollups, most_recent_hour=rollups[0]
    )
    assert status.total_count == 1000
    assert status.error_count == 5
    assert status.error_budget_total == pytest.approx(10.0)  # 1% of 1000
    assert status.error_budget_consumed == 5
    assert status.error_budget_remaining_percent == pytest.approx(50.0)  # half the budget spent


def test_budget_can_go_negative_when_blown():
    rollups = [HourlyCount(total_count=1000, error_count=50)]
    status = compute_slo_status(
        "checkout", target_percent=99.0, window_days=30, window_rollups=rollups, most_recent_hour=rollups[0]
    )
    # budget was 10 errors, 50 actually happened -- 5x over
    assert status.error_budget_remaining_percent == pytest.approx(-400.0)


def test_burn_rate_one_matches_sustainable_pace():
    # Observed error rate this hour exactly equals the allowed rate ->
    # burn rate should be 1.0 (on pace to exhaust the budget exactly at
    # window's end, not before).
    recent = HourlyCount(total_count=1000, error_count=10)  # 1% error rate
    status = compute_slo_status(
        "checkout", target_percent=99.0, window_days=30, window_rollups=[recent], most_recent_hour=recent
    )
    assert status.burn_rate_1h == pytest.approx(1.0)
    assert status.is_fast_burning is False


def test_fast_burn_flagged_above_threshold():
    # target 99.9 -> allowed rate 0.1%; observed 5% error rate this hour
    # -> burn rate 50x, comfortably past the 14.4x fast-burn threshold.
    recent = HourlyCount(total_count=1000, error_count=50)
    status = compute_slo_status(
        "api-gateway", target_percent=99.9, window_days=30, window_rollups=[recent], most_recent_hour=recent
    )
    assert status.burn_rate_1h == pytest.approx(50.0)
    assert status.burn_rate_1h >= FAST_BURN_THRESHOLD
    assert status.is_fast_burning is True


def test_hundred_percent_target_treats_any_error_as_instant_blow():
    recent = HourlyCount(total_count=1000, error_count=1)
    status = compute_slo_status(
        "critical-svc", target_percent=100.0, window_days=30, window_rollups=[recent], most_recent_hour=recent
    )
    assert status.error_budget_total == 0
    assert status.error_budget_remaining_percent is None
    assert status.burn_rate_1h == float("inf")
    assert status.is_fast_burning is True


def test_hundred_percent_target_with_zero_errors_is_not_burning():
    recent = HourlyCount(total_count=1000, error_count=0)
    status = compute_slo_status(
        "critical-svc", target_percent=100.0, window_days=30, window_rollups=[recent], most_recent_hour=recent
    )
    assert status.burn_rate_1h == 0.0
    assert status.is_fast_burning is False


def test_most_recent_hour_with_no_traffic_gives_no_burn_rate():
    history = [HourlyCount(total_count=1000, error_count=5)]
    empty_hour = HourlyCount(total_count=0, error_count=0)
    status = compute_slo_status(
        "checkout", target_percent=99.0, window_days=30, window_rollups=history, most_recent_hour=empty_hour
    )
    assert status.burn_rate_1h is None
    assert status.is_fast_burning is False