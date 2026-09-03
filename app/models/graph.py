"""
The behavioral graph: nodes are services *discovered* from span data
(never manually configured), edges are caller->callee relationships
derived from span parent/child linkage. Each edge carries a rolling
baseline that the bottleneck engine and incident detector both read.

This is deliberately a thin, queryable representation (not an in-memory
graph library) so the API layer and both background engines can share
one source of truth without duplicating state.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Float, ForeignKey, UniqueConstraint, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ServiceNode(Base):
    __tablename__ = "service_nodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # --- Structural risk baseline -- same current/reference split as
    # ServiceEdge's latency baseline, but for the bottleneck engine's
    # risk_score instead. "current" updates every bottleneck scan (see
    # app/bottleneck/baseline.py); "reference" is promoted from it on
    # a slower cadence (see app/bottleneck/reference.py). This is what
    # lets "is this service unusually risky" be judged against ITS OWN
    # normal, rather than one fixed threshold applied to every service
    # regardless of its typical fan-in/criticality. ---
    current_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score_variance: Mapped[float] = mapped_column(Float, default=0.0)  # Welford, own spread
    risk_scan_count: Mapped[int] = mapped_column(Integer, default=0)

    reference_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    reference_risk_stddev: Mapped[float] = mapped_column(Float, default=0.0)
    reference_risk_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_service_workspace_name"),)


class ServiceEdge(Base):
    """
    A directed caller -> callee relationship, with TWO decoupled baselines:

    - "current" fields: a fast EWMA updated on every span, reflecting what
      the edge is doing *right now*.
    - "reference" fields: a slow snapshot (see app/graph/reference.py),
      refreshed on a longer cadence, reflecting what's *normal*.

    Anomaly detection z-scores "current" against "reference". A single
    shared EWMA can't serve both roles -- if the same fast-moving number
    were used as "normal," a real incident would just get absorbed into
    the baseline as it happened, and nothing would ever look anomalous.
    """
    __tablename__ = "service_edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    caller: Mapped[str] = mapped_column(String(255), nullable=False)
    callee: Mapped[str] = mapped_column(String(255), nullable=False)

    # --- Current (fast EWMA, updated per-span) ---
    current_latency_ms_p50: Mapped[float] = mapped_column(Float, default=0.0)
    current_latency_ms_p99: Mapped[float] = mapped_column(Float, default=0.0)
    current_error_rate: Mapped[float] = mapped_column(Float, default=0.0)
    current_latency_variance: Mapped[float] = mapped_column(Float, default=0.0)  # Welford, for this edge's own spread

    # --- Reference (slow snapshot, refreshed periodically) ---
    reference_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    reference_error_rate: Mapped[float] = mapped_column(Float, default=0.0)
    reference_latency_stddev: Mapped[float] = mapped_column(Float, default=0.0)
    reference_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    baseline_throughput_rps: Mapped[float] = mapped_column(Float, default=0.0)

    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (UniqueConstraint("workspace_id", "caller", "callee", name="uq_edge_workspace_pair"),)