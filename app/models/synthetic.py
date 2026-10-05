"""
Active synthetic monitoring's two tables.

Everything else in Ghost Protocol is passive: it analyzes telemetry it
received. That has a real blind spot -- a service that crashes and
stops emitting spans entirely produces no telemetry at all, so nothing
here (anomaly detection, bottleneck scoring, SLO burn-rate) can ever
flag it, since every one of those detectors works by comparing *new*
data against a baseline. No data means no comparison, means no
incident, means total silence looks identical to "nothing's running
that would generate traffic right now." Synthetic monitoring is the
one part of Ghost that doesn't wait for data to arrive -- it generates
its own, by probing a URL the workspace registers and opening/resolving
a real Incident (same model, same notification webhook, same dashboard)
based on what the probe itself observes.

SyntheticCheck is the registered probe + its own small state machine,
same cooldown-style shape as SLODefinition.alert_fired_at: a check
accumulates consecutive_failures, and once that crosses
failure_threshold it opens an Incident and records open_incident_id so
it doesn't open a second one on every subsequent failed probe. The
first successful probe after that resolves the incident and clears the
state, ready to fire again on the next outage. last_probed_at (not a
wall-clock modulo like the hourly/5-minute tick blocks) is what makes
the check's own interval_seconds meaningful regardless of how often or
irregularly the external tick itself actually fires.

SyntheticCheckResult is the raw probe history -- what the Pipeline
Health-style view on this feature reads from. Capped per-check (see
app/synthetic/prober.py) rather than aged out on a schedule like raw
telemetry, since the volume per check is small and bounded by
definition (one row per probe, at most one probe per check per tick).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SyntheticCheck(Base):
    __tablename__ = "synthetic_checks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False, default="GET")

    # A probe is a "success" if the response status falls in
    # [expected_status_min, expected_status_max] -- a range, not a
    # single value, so a company that treats any 2xx as healthy
    # doesn't have to register five near-identical checks.
    expected_status_min: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    expected_status_max: Mapped[int] = mapped_column(Integer, nullable=False, default=299)

    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    failure_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # --- mutable state, same role as SLODefinition.alert_fired_at ---
    last_probed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=True
    )


class SyntheticCheckResult(Base):
    __tablename__ = "synthetic_check_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    check_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("synthetic_checks.id"), nullable=False, index=True
    )
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)