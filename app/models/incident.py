import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Float, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Incident(Base):
    """
    A correlated set of anomalies on the behavioral graph, treated as one
    unit for diagnosis. Correlation logic lives in app/incident/correlate.py;
    this table is just the persisted result plus its evolving timeline.
    """
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open")  # open / diagnosing / resolved / dismissed
    severity: Mapped[str] = mapped_column(String(16), default="medium")  # low / medium / high / critical

    primary_service: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The raw anomaly evidence that triggered/grew this incident -- a list
    # of {edge, metric, observed, baseline, zscore, at} objects. This is
    # exactly what gets serialized into the ReasoningProvider evidence
    # payload, so the LLM's input is always inspectable here too.
    evidence: Mapped[list] = mapped_column(JSONB, default=list)

    events: Mapped[list["Event"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    reasoning_results: Mapped[list["ReasoningResult"]] = relationship(back_populates="incident", cascade="all, delete-orphan")


class Event(Base):
    """One timeline entry on an incident (anomaly detected, correlated, diagnosed, resolved, etc.)."""
    __tablename__ = "incident_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(String(1024), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    incident: Mapped["Incident"] = relationship(back_populates="events")


class ReasoningResult(Base):
    """
    Persisted output of ReasoningProvider.diagnose(), including which RAG
    documents were retrieved and cited, so every recommendation stays
    traceable back to its evidence and sources.
    """
    __tablename__ = "reasoning_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), nullable=False)

    provider_tier: Mapped[str] = mapped_column(String(32), nullable=False)  # standard / byo
    hypothesis: Mapped[str] = mapped_column(String(4096), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    proposed_changes: Mapped[list] = mapped_column(JSONB, default=list)
    reasoning_trace: Mapped[list] = mapped_column(JSONB, default=list)
    cited_documents: Mapped[list] = mapped_column(JSONB, default=list)  # [{doc_id, title, chunk, score}]

    simulation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # filled in by simulation engine

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    incident: Mapped["Incident"] = relationship(back_populates="reasoning_results")
