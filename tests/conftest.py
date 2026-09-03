"""
Shared fixtures. Ghost Protocol's models (ServiceEdge, ServiceNode) are
plain SQLAlchemy declarative classes -- instantiating them directly,
without a session, works fine and needs no database at all, since
nothing here touches the DB. The one thing to watch: `default=` on a
mapped_column only applies at flush time, not on direct construction,
so these factories set every field the baseline/engine code actually
reads rather than relying on column defaults that won't have fired yet.
"""
import os

# GHOST_SECRET_KEY must be set before anything imports app.core.config
# (Settings is cached via lru_cache on first call) or app.core.crypto
# (same caching on its Fernet instance) -- app.core.session, used by
# test_session.py, needs a real Fernet-valid key or it raises
# immediately. Setting this here, before any `from app...` import
# below, guarantees it's in the environment the first time anything
# reads it, regardless of which test file pytest happens to collect
# first.
os.environ.setdefault("GHOST_SECRET_KEY", "1FJMdMuNdNTIEpA_2XwAOA3xkRJClyoFqU6xAX4Hr2s=")

import uuid

import pytest

from app.models.graph import ServiceEdge, ServiceNode


def make_edge(caller="checkout", callee="redis", **overrides) -> ServiceEdge:
    defaults = dict(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        caller=caller,
        callee=callee,
        current_latency_ms_p50=0.0,
        current_latency_ms_p99=0.0,
        current_error_rate=0.0,
        current_latency_variance=0.0,
        reference_latency_ms=0.0,
        reference_error_rate=0.0,
        reference_latency_stddev=0.0,
        reference_updated_at=None,
        baseline_throughput_rps=0.0,
        sample_count=0,
    )
    defaults.update(overrides)
    return ServiceEdge(**defaults)


def make_node(name="redis", **overrides) -> ServiceNode:
    defaults = dict(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name=name,
        current_risk_score=0.0,
        risk_score_variance=0.0,
        risk_scan_count=0,
        reference_risk_score=0.0,
        reference_risk_stddev=0.0,
        reference_risk_updated_at=None,
    )
    defaults.update(overrides)
    return ServiceNode(**defaults)


@pytest.fixture
def edge_factory():
    return make_edge


@pytest.fixture
def node_factory():
    return make_node