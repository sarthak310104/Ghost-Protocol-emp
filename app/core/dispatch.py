"""
Every place in this codebase that would enqueue a Celery task goes
through this instead of calling .delay() directly, so there's exactly
one place that knows about GHOST_SYNC_MODE rather than an `if` scattered
across every call site.

Celery task objects are callable directly, not just via .delay() --
task(*args) runs the task body synchronously in the current process,
identical to calling a plain function, while task.delay(*args) enqueues
it for a separate worker to pick up. That's the entire mechanism this
relies on: sync mode isn't a reimplementation of these tasks, it's the
exact same task bodies, just invoked without the broker in between.
"""
from app.core.config import get_settings


def dispatch(task, *args) -> None:
    settings = get_settings()
    if settings.ghost_sync_mode:
        task(*args)
    else:
        task.delay(*args)