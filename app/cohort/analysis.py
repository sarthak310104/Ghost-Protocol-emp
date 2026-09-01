"""
Concurrent cohort comparison: if a company's canary/gradual rollout
tags spans with a registered attribute (see app/models/cohort.py), this
compares latency between whatever values of that attribute are
currently co-occurring on the same edge -- e.g. 8% of checkout->redis
traffic tagged config.redis_ttl_seconds=300 against the other 92% still
at 30, observed over the same recent window.

This is a genuinely different kind of evidence than the mean-reversion
simulation engine produces: mean-reversion projects "what if this
metric returns to its own past," cohort comparison observes "what two
concurrently-running configurations actually looked like happening
at the same time." Neither claims causation -- the difference is
scale of confidence: two groups running concurrently, unconfounded by
whatever else changed that week, is stronger evidence than a before/
after comparison, but it's still an association, not a randomized
experiment. The output says exactly that.

Requires nothing at ingestion time -- Span.attributes already stores
every OTel span attribute as JSONB, so this queries data that's already
there the moment a company starts tagging spans.
"""
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, aliased

from app.models.telemetry import Span

_MIN_SAMPLE_SIZE = 30  # per cohort, before a comparison is trusted at all
_Z_95 = 1.96


@dataclass
class CohortStat:
    value: str
    sample_count: int
    mean_latency_ms: float
    stddev_latency_ms: float


@dataclass
class CohortComparison:
    baseline_cohort: str
    compared_cohort: str
    difference_pct: float
    ci_95_low_pct: float
    ci_95_high_pct: float
    method: str


@dataclass
class CohortAnalysisResult:
    edge: str
    dimension: str
    window_minutes: int
    cohorts: list[CohortStat] = field(default_factory=list)
    comparison: CohortComparison | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        return {
            "edge": self.edge,
            "dimension": self.dimension,
            "window_minutes": self.window_minutes,
            "cohorts": [c.__dict__ for c in self.cohorts],
            "comparison": self.comparison.__dict__ if self.comparison else None,
            "note": self.note,
        }


def _fetch_cohort_spans(
    db: Session, workspace_id: uuid.UUID, caller: str, callee: str,
    attribute_key: str, window_minutes: int,
) -> list[tuple[float, str | None]]:
    """
    Self-joins spans to their parent within the same trace to identify
    which edge (caller->callee) each child span belongs to -- edges
    aren't stored per-span, only derived at ingestion time for the
    rolling baseline, so recovering them for historical analysis means
    re-deriving the same parent/child relationship from raw spans.
    """
    child = aliased(Span)
    parent = aliased(Span)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

    stmt = (
        select(child.duration_ms, child.attributes[attribute_key].astext)
        .join(parent, and_(child.trace_id == parent.trace_id, child.parent_span_id == parent.span_id))
        .where(
            child.workspace_id == workspace_id,
            parent.service_name == caller,
            child.service_name == callee,
            child.started_at >= cutoff,
            child.attributes.has_key(attribute_key),
        )
    )
    return db.execute(stmt).all()


def _compute_stats(rows: list[tuple[float, str | None]]) -> list[CohortStat]:
    groups: dict[str, list[float]] = defaultdict(list)
    for duration_ms, cohort_value in rows:
        if cohort_value is None:
            continue
        groups[cohort_value].append(duration_ms)

    stats = []
    for value, durations in groups.items():
        n = len(durations)
        mean = sum(durations) / n
        variance = sum((d - mean) ** 2 for d in durations) / n if n > 1 else 0.0
        stats.append(CohortStat(
            value=value, sample_count=n,
            mean_latency_ms=round(mean, 2),
            stddev_latency_ms=round(variance ** 0.5, 2),
        ))
    return sorted(stats, key=lambda s: s.sample_count, reverse=True)


def _compute_comparison(stats: list[CohortStat]) -> CohortComparison | None:
    """
    Two-sample z-approximation on the difference of means, using the two
    largest-by-sample-size cohorts. Requires both cohorts to individually
    clear _MIN_SAMPLE_SIZE -- below that, a percentage difference is more
    likely to be sampling noise than a real effect, and reporting it
    with false precision would be worse than reporting nothing.
    """
    eligible = [s for s in stats if s.sample_count >= _MIN_SAMPLE_SIZE]
    if len(eligible) < 2:
        return None

    baseline, compared = eligible[0], eligible[1]
    if baseline.mean_latency_ms <= 0:
        return None

    se_baseline = baseline.stddev_latency_ms / math.sqrt(baseline.sample_count)
    se_compared = compared.stddev_latency_ms / math.sqrt(compared.sample_count)
    se_diff = math.sqrt(se_baseline ** 2 + se_compared ** 2)

    diff = compared.mean_latency_ms - baseline.mean_latency_ms
    diff_pct = 100 * diff / baseline.mean_latency_ms
    ci_low_pct = 100 * (diff - _Z_95 * se_diff) / baseline.mean_latency_ms
    ci_high_pct = 100 * (diff + _Z_95 * se_diff) / baseline.mean_latency_ms

    return CohortComparison(
        baseline_cohort=baseline.value,
        compared_cohort=compared.value,
        difference_pct=round(diff_pct, 1),
        ci_95_low_pct=round(min(ci_low_pct, ci_high_pct), 1),
        ci_95_high_pct=round(max(ci_low_pct, ci_high_pct), 1),
        method="two_sample_z_approximation",
    )


def run_cohort_analysis(
    db: Session, workspace_id: uuid.UUID, caller: str, callee: str,
    attribute_key: str, window_minutes: int = 60,
) -> CohortAnalysisResult:
    """Sync entry point -- used from Celery tasks (see app/workers/tasks.py)."""
    edge = f"{caller}->{callee}"
    rows = _fetch_cohort_spans(db, workspace_id, caller, callee, attribute_key, window_minutes)
    return _assemble_result(edge, attribute_key, window_minutes, rows)


async def _fetch_cohort_spans_async(
    db, workspace_id: uuid.UUID, caller: str, callee: str,
    attribute_key: str, window_minutes: int,
) -> list[tuple[float, str | None]]:
    child = aliased(Span)
    parent = aliased(Span)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

    stmt = (
        select(child.duration_ms, child.attributes[attribute_key].astext)
        .join(parent, and_(child.trace_id == parent.trace_id, child.parent_span_id == parent.span_id))
        .where(
            child.workspace_id == workspace_id,
            parent.service_name == caller,
            child.service_name == callee,
            child.started_at >= cutoff,
            child.attributes.has_key(attribute_key),
        )
    )
    result = await db.execute(stmt)
    return result.all()


async def run_cohort_analysis_async(
    db, workspace_id: uuid.UUID, caller: str, callee: str,
    attribute_key: str, window_minutes: int = 60,
) -> CohortAnalysisResult:
    """Async entry point -- used from FastAPI routes (see app/api/routes/cohorts.py)."""
    edge = f"{caller}->{callee}"
    rows = await _fetch_cohort_spans_async(db, workspace_id, caller, callee, attribute_key, window_minutes)
    return _assemble_result(edge, attribute_key, window_minutes, rows)


def _assemble_result(edge: str, attribute_key: str, window_minutes: int, rows: list[tuple[float, str | None]]) -> CohortAnalysisResult:
    if not rows:
        return CohortAnalysisResult(
            edge=edge, dimension=attribute_key, window_minutes=window_minutes,
            note="No spans on this edge carried this attribute in the given window.",
        )

    stats = _compute_stats(rows)
    if len(stats) < 2:
        return CohortAnalysisResult(
            edge=edge, dimension=attribute_key, window_minutes=window_minutes, cohorts=stats,
            note="Only one cohort value observed -- no concurrent comparison is possible yet.",
        )

    comparison = _compute_comparison(stats)
    note = None if comparison else (
        f"Cohorts found, but at least one has fewer than {_MIN_SAMPLE_SIZE} samples -- "
        "too small to compare reliably yet."
    )
    return CohortAnalysisResult(
        edge=edge, dimension=attribute_key, window_minutes=window_minutes,
        cohorts=stats, comparison=comparison, note=note,
    )