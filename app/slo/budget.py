"""
Pure error-budget and burn-rate math over ServiceSLIRollup rows --no DB
or network access, so this is the testable core; app/slo/status.py (the
DB-touching wrapper, added in the API commit) is the thin shell around
it, same split as app/deployments/drift.py and app/reliability/trends.py.

Error budget: at a target_percent (e.g. 99.9) over window_days (e.g.
30), the budget is how many requests are "allowed" to fail without
breaking that target -- total_count * (1 - target_percent/100). Budget
consumed is however many actually failed in that window; remaining is
the difference, which can go negative (budget blown).

Burn rate is the fast-warning signal, not the budget total: it compares
the error rate in a *short* recent window (one hour -- the rollup
granularity) against the error rate the target allows. A burn rate of
1.0 means errors are happening at exactly the sustainable pace (the
whole window's budget would be spent exactly at the window's end); a
burn rate of 14.4 means the current hour's error rate would exhaust an
entire 30-day budget in about 2 days if it kept up. 14.4 is the
standard one-hour fast-burn multiplier from Google's SRE workbook
multi-window burn-rate alerting scheme -- not something invented here,
reused because it's a well-reasoned, widely-used threshold rather than
an arbitrary number.
"""
from dataclasses import dataclass

# Standard one-hour fast-burn threshold (Google SRE workbook
# multi-window burn-rate alerting). Below this, burn is within or close
# to sustainable pace; at/above it, the budget would be gone well before
# the window ends if it kept up.
FAST_BURN_THRESHOLD = 14.4


@dataclass
class HourlyCount:
    total_count: int
    error_count: int


@dataclass
class SLOStatus:
    service_name: str
    target_percent: float
    window_days: int

    total_count: int
    error_count: int
    actual_percent: float | None  # None when there's no traffic at all in the window

    error_budget_total: float
    error_budget_consumed: int
    error_budget_remaining_percent: float | None  # None when error_budget_total is 0 (a 100% target)

    burn_rate_1h: float | None  # None when the most recent hour had no traffic
    is_fast_burning: bool

    def to_dict(self) -> dict:
        return {
            "service_name": self.service_name,
            "target_percent": self.target_percent,
            "window_days": self.window_days,
            "total_count": self.total_count,
            "error_count": self.error_count,
            "actual_percent": self.actual_percent,
            "error_budget_total": self.error_budget_total,
            "error_budget_consumed": self.error_budget_consumed,
            "error_budget_remaining_percent": self.error_budget_remaining_percent,
            # inf (the 100%-target/any-error case) isn't valid JSON --
            # swapped for null here, same substitution
            # build_slo_burn_payload makes for the webhook payload.
            "burn_rate_1h": None if self.burn_rate_1h == float("inf") else self.burn_rate_1h,
            "is_fast_burning": self.is_fast_burning,
        }


def compute_slo_status(
    service_name: str,
    target_percent: float,
    window_days: int,
    window_rollups: list[HourlyCount],
    most_recent_hour: HourlyCount | None,
) -> SLOStatus:
    """
    window_rollups: every ServiceSLIRollup row inside the SLO's window
    (any order). most_recent_hour: the single most recent hour's row
    (or None if there isn't one yet / it had no traffic) -- kept
    separate from window_rollups rather than re-derived from it, since
    the caller already knows which row is most recent from the query
    that fetched them.
    """
    total_count = sum(r.total_count for r in window_rollups)
    error_count = sum(r.error_count for r in window_rollups)
    actual_percent = None if total_count == 0 else 100.0 * (total_count - error_count) / total_count

    allowed_error_rate = 1 - (target_percent / 100.0)
    error_budget_total = total_count * allowed_error_rate
    error_budget_remaining_percent = (
        None if error_budget_total == 0 else 100.0 * (error_budget_total - error_count) / error_budget_total
    )

    burn_rate_1h = None
    if most_recent_hour is not None and most_recent_hour.total_count > 0:
        observed_error_rate = most_recent_hour.error_count / most_recent_hour.total_count
        if allowed_error_rate > 0:
            burn_rate_1h = observed_error_rate / allowed_error_rate
        else:
            # A 100% target allows zero errors -- any observed error at
            # all is an instant budget blow, not a ratio.
            burn_rate_1h = float("inf") if observed_error_rate > 0 else 0.0

    is_fast_burning = burn_rate_1h is not None and burn_rate_1h >= FAST_BURN_THRESHOLD

    return SLOStatus(
        service_name=service_name,
        target_percent=target_percent,
        window_days=window_days,
        total_count=total_count,
        error_count=error_count,
        actual_percent=actual_percent,
        error_budget_total=error_budget_total,
        error_budget_consumed=error_count,
        error_budget_remaining_percent=error_budget_remaining_percent,
        burn_rate_1h=burn_rate_1h,
        is_fast_burning=is_fast_burning,
    )