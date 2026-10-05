"""
Retrospective comparison for a specific past config change -- real
edge metrics in a window right before a given timestamp vs a window
right after, using the same two-sample statistical method
app/cohort/analysis.py already proved out for concurrent cohorts.

This is the weaker-evidence sibling of that module, not a replacement
for it: a concurrent cohort comparison is unconfounded by whatever
else happened that week, since both groups ran at the same time.
Before/after on a single timeline has no such guarantee -- anything
else that changed in the same window (traffic mix, an unrelated
deploy, time of day) is baked into the difference along with whatever
effect the config change itself had. The output says this explicitly;
it is not something this module tries to control for, because doing
so honestly would need the sandboxed-replica infrastructure that's
deliberately out of scope (see app/simulation/engine.py's docstring
for the same line drawn on the simulation side).

Bounded by raw telemetry retention, in a way the config-drift list
itself (app/deployments/drift.py) is not: Deployment rows are never
pruned, so a drift event from weeks ago still shows up there, but the
raw Span rows this module queries for its "before" window are (see
app.ingestion.retention.prune_old_telemetry,
GHOST_TELEMETRY_RETENTION_HOURS, default 24h). A config change older
than that retention window has no surviving "before" data -- this
module reports that plainly rather than silently comparing against an
empty window.
"""
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, aliased

from app.models.telemetry import Span

_MIN_SAMPLE_SIZE = 30  # per window, before a comparison is trusted at all -- same floor as cohort analysis
_Z_95 = 1.96


@dataclass
class PeriodStat:
    label: str  # "before" or "after"
    sample_count: int
    mean_latency_ms: float
    stddev_latency_ms: float
    error_rate: float  # fraction of spans in this window with status_code == "ERROR"


@dataclass
class RetrospectiveComparison:
    difference_pct: float
    ci_95_low_pct: float
    ci_95_high_pct: float
    method: str


@dataclass
class RetrospectiveResult:
    edge: str
    changed_at: datetime
    window_minutes: int
    before: PeriodStat | None
    after: PeriodStat | None
    comparison: RetrospectiveComparison | None
    note: str | None

    def to_dict(self) -> dict:
        return {
            "edge": self.edge,
            "changed_at": self.changed_at.isoformat(),
            "window_minutes": self.window_minutes,
            "before": self.before.__dict__ if self.before else None,
            "after": self.after.__dict__ if self.after else None,
            "comparison": self.comparison.__dict__ if self.comparison else None,
            "note": self.note,
        }


def _period_query(caller: str, callee: str, workspace_id: uuid.UUID, start: datetime, end: datetime):
    """
    Same parent/child self-join app/cohort/analysis.py uses to recover
    which edge a span belongs to -- edges aren't stored per-span, only
    derived at ingestion time for the rolling baseline. No attribute
    filter here, unlike the cohort version: every span on the edge in
    the window counts, not just ones carrying a registered dimension.
    """
    child = aliased(Span)
    parent = aliased(Span)
    return (
        select(child.duration_ms, child.status_code)
        .join(parent, and_(child.trace_id == parent.trace_id, child.parent_span_id == parent.span_id))
        .where(
            child.workspace_id == workspace_id,
            parent.service_name == caller,
            child.service_name == callee,
            child.started_at >= start,
            child.started_at < end,
        )
    )


def _compute_stat(label: str, rows: list[tuple[float, str]]) -> PeriodStat | None:
    if not rows:
        return None
    durations = [r[0] for r in rows]
    n = len(durations)
    mean = sum(durations) / n
    variance = sum((d - mean) ** 2 for d in durations) / n if n > 1 else 0.0
    error_count = sum(1 for _, status_code in rows if status_code == "ERROR")
    return PeriodStat(
        label=label, sample_count=n,
        mean_latency_ms=round(mean, 2),
        stddev_latency_ms=round(variance ** 0.5, 2),
        error_rate=round(error_count / n, 4),
    )


def _compute_comparison(before: PeriodStat | None, after: PeriodStat | None) -> tuple[RetrospectiveComparison | None, str | None]:
    """
    Two-sample z-approximation on the difference of means, before vs
    after -- same math as app/cohort/analysis.py's
    _compute_comparison, just fixed to exactly these two periods
    rather than picking the two largest-by-sample-size groups (there
    are only ever two groups here, and both matter regardless of which
    happens to have more samples).
    """
    if before is None or after is None:
        return None, (
            "No spans on this edge in one or both windows -- nothing to compare. "
            "A config change older than the telemetry retention window has no "
            "surviving \"before\" data."
        )
    if before.sample_count < _MIN_SAMPLE_SIZE or after.sample_count < _MIN_SAMPLE_SIZE:
        return None, f"At least one window has fewer than {_MIN_SAMPLE_SIZE} samples -- too small to compare reliably yet."
    if before.mean_latency_ms <= 0:
        return None, "The \"before\" window has zero mean latency -- can't compute a percentage difference against it."

    se_before = before.stddev_latency_ms / math.sqrt(before.sample_count)
    se_after = after.stddev_latency_ms / math.sqrt(after.sample_count)
    se_diff = math.sqrt(se_before ** 2 + se_after ** 2)

    diff = after.mean_latency_ms - before.mean_latency_ms
    diff_pct = 100 * diff / before.mean_latency_ms
    ci_low_pct = 100 * (diff - _Z_95 * se_diff) / before.mean_latency_ms
    ci_high_pct = 100 * (diff + _Z_95 * se_diff) / before.mean_latency_ms

    return RetrospectiveComparison(
        difference_pct=round(diff_pct, 1),
        ci_95_low_pct=round(min(ci_low_pct, ci_high_pct), 1),
        ci_95_high_pct=round(max(ci_low_pct, ci_high_pct), 1),
        method="two_sample_z_approximation_before_after",
    ), None


def _assemble_result(edge: str, changed_at: datetime, window_minutes: int, before_rows, after_rows) -> RetrospectiveResult:
    before = _compute_stat("before", before_rows)
    after = _compute_stat("after", after_rows)
    comparison, note = _compute_comparison(before, after)
    return RetrospectiveResult(
        edge=edge, changed_at=changed_at, window_minutes=window_minutes,
        before=before, after=after, comparison=comparison, note=note,
    )


def run_retrospective_comparison(
    db: Session, workspace_id: uuid.UUID, caller: str, callee: str,
    changed_at: datetime, window_minutes: int = 60,
) -> RetrospectiveResult:
    """Sync entry point."""
    edge = f"{caller}->{callee}"
    before_start = changed_at - timedelta(minutes=window_minutes)
    after_end = changed_at + timedelta(minutes=window_minutes)
    before_rows = db.execute(_period_query(caller, callee, workspace_id, before_start, changed_at)).all()
    after_rows = db.execute(_period_query(caller, callee, workspace_id, changed_at, after_end)).all()
    return _assemble_result(edge, changed_at, window_minutes, before_rows, after_rows)


async def run_retrospective_comparison_async(
    db, workspace_id: uuid.UUID, caller: str, callee: str,
    changed_at: datetime, window_minutes: int = 60,
) -> RetrospectiveResult:
    """Async entry point -- used from FastAPI routes (see app/api/routes/deployments.py)."""
    edge = f"{caller}->{callee}"
    before_start = changed_at - timedelta(minutes=window_minutes)
    after_end = changed_at + timedelta(minutes=window_minutes)
    before_result = await db.execute(_period_query(caller, callee, workspace_id, before_start, changed_at))
    after_result = await db.execute(_period_query(caller, callee, workspace_id, changed_at, after_end))
    return _assemble_result(edge, changed_at, window_minutes, before_result.all(), after_result.all())