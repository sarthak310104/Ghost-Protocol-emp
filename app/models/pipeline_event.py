"""
A per-workspace log of "did Ghost's own pipeline actually run for me,
and did it succeed" -- deliberately scoped to one workspace at a time,
not a platform-operator view of infrastructure health across every
tenant. A workspace should be able to see that its own anomaly scan
ran 40 seconds ago and succeeded, without seeing anything about any
other company's data or Ghost's own CPU/memory.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    kind: Mapped[str] = mapped_column(String(64), nullable=False)  # "anomaly_scan" | "bottleneck_scan"
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    is_error: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)