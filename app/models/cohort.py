"""
A workspace explicitly registers an attribute key it wants Ghost to
track as a "cohort dimension" -- e.g. a canary rollout tagging spans
with `config.redis_ttl_seconds=300` for 10% of traffic. This is
deliberately explicit rather than auto-detected: Ghost doesn't go
hunting through every span attribute looking for things that vary,
it only ever compares along a dimension the company has told it
matters. Consistent with the rest of the platform's "evidence, not
inference" posture.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CohortDimension(Base):
    __tablename__ = "cohort_dimensions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    attribute_key: Mapped[str] = mapped_column(String(255), nullable=False)  # e.g. "config.redis_ttl_seconds"
    label: Mapped[str] = mapped_column(String(255), nullable=False)  # e.g. "Redis TTL"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)