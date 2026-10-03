"""
SLO tracking's two tables.

ServiceSLIRollup is the piece that makes this possible at all: raw
spans are pruned after ghost_telemetry_retention_hours (24h default --
see app/ingestion/retention.py), but an SLO window is typically 30
days. Querying raw spans for a 30-day error rate would silently return
almost nothing once the window outlives the retention cutoff. So, like
Incident for reliability trends, this is durable derived state --
one row per (workspace, service, hour), written by the hourly rollup
task *before* that hour's raw spans get pruned, and never pruned
itself. A 30-day SLO is then just a sum over ~720 rollup rows instead
of a query over everything spans.

SLODefinition is just the target a workspace sets per service --
target_percent (e.g. 99.9) over window_days (e.g. 30). Computing
budget/burn-rate from a definition + the rollups is done in
app/slo/budget.py, not stored here -- it's always derived fresh from
current rollup data, same reasoning as reliability trends not storing
its own computed buckets.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ServiceSLIRollup(Base):
    __tablename__ = "service_sli_rollups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    service_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Always the top of the hour (minute/second/microsecond zeroed) --
    # the rollup task's own bucketing, not a user-facing value.
    hour_bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("workspace_id", "service_name", "hour_bucket", name="uq_sli_rollup_workspace_service_hour"),
    )


class SLODefinition(Base):
    __tablename__ = "slo_definitions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    service_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # e.g. 99.9 -- a percentage, not a fraction, to match how these are
    # always spoken/written ("ninety-nine point nine").
    target_percent: Mapped[float] = mapped_column(Float, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Set when a burn-rate alert has fired and not yet cleared -- the
    # cooldown state for the hourly check in app/slo/alerts.py. Null
    # means "not currently alerting"; a non-null value means an alert
    # is active and won't re-fire until the burn clears first.
    alert_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("workspace_id", "service_name", name="uq_slo_workspace_service"),
    )