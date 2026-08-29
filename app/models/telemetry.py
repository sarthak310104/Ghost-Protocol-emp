"""
Raw ingested telemetry. These two tables are converted to TimescaleDB
hypertables (see migrations/001_hypertables.sql) partitioned on their
timestamp column -- this is what lets Ghost Protocol hold months of
trace/metric history per workspace without the query planner falling
over.

Nothing here is service-specific by schema; `service_name` is just a
string pulled off the incoming OTel resource attributes. New services
appear automatically the first time a span references them.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Float, BigInteger, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Span(Base):
    __tablename__ = "spans"

    # Composite-ish identity: Timescale hypertables want the partitioning
    # column (started_at) in every unique constraint, so we don't rely on
    # a bare-UUID primary key alone for uniqueness at the DB level.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    span_id: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    service_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    span_name: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="INTERNAL")

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)

    status_code: Mapped[str] = mapped_column(String(16), default="UNSET")  # OK / ERROR / UNSET
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        Index("ix_spans_workspace_started", "workspace_id", "started_at"),
        Index("ix_spans_workspace_service_started", "workspace_id", "service_name", "started_at"),
    )


class MetricPoint(Base):
    __tablename__ = "metric_points"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    service_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)

    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        Index("ix_metrics_workspace_service_metric_time", "workspace_id", "service_name", "metric_name", "recorded_at"),
    )
