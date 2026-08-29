"""
A deployment marker: "this service went to this version at this time."
Recorded via a simple API call (see app/api/routes/deployments.py) --
either a CI/CD pipeline step hits it directly, or an OTel resource
attribute convention (e.g. `service.version` changing) could populate it
later. For now it's an explicit, deliberately simple ingestion path
rather than inferred from telemetry, since inferring "this was a
deployment" from span/metric data alone is unreliable.
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


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    service_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(255), nullable=False)
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    notes: Mapped[str | None] = mapped_column(String(1024), nullable=True)
