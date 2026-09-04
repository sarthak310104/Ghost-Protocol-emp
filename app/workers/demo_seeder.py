"""
Pulled out of app/workers/tasks.py deliberately -- everything else in
that module imports Celery, which is exactly the kind of heavyweight,
DB-adjacent dependency the rest of this codebase's pure logic
(app/graph/baseline.py, app/bottleneck/engine.py, app/cohort/analysis.py,
etc.) stays free of, specifically so it's testable without a database
or a message broker. This one function belongs with that group, not
with the Celery task that calls it.
"""
import datetime


def demo_cycle_is_spiking(now: datetime.datetime, cycle_seconds: int, spike_seconds: int) -> bool:
    """
    Given the current time and the cycle's shape, is this moment inside
    the spike window? Deterministic and stateless -- any worker
    process, at any time, computes the same answer without needing to
    share state, which is what makes this safe to call from a
    scheduled task that could run on a different process each time.
    """
    phase = int(now.timestamp()) % cycle_seconds
    return phase >= (cycle_seconds - spike_seconds)