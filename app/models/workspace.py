"""
Workspace is the tenancy boundary inside one self-hosted Ghost Protocol
deployment. A company typically runs a single workspace, but nothing
prevents e.g. separate "production" / "staging" workspaces within the
same self-hosted install. This is NOT multi-tenant SaaS -- there is no
concept of a Ghost-Protocol-hosted customer directory. The workspace
purely scopes ingestion, the behavioral graph, RAG documents, and the
reasoning-provider configuration.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Optional external reasoning/analysis connection for this workspace.
    # Ghost Protocol does not implement reasoning itself -- it POSTs
    # incident evidence to whatever endpoint is configured here and
    # expects a structured response back. Any service implementing that
    # request/response contract can sit behind this URL; Ghost Protocol
    # doesn't need to know what it is.
    reasoning_endpoint_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reasoning_api_key_encrypted: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    reasoning_provider_label: Mapped[str] = mapped_column(String(64), default="unconfigured")  # informational only

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class ApiKey(Base):
    """
    Ingestion credential. The OTel collector authenticates with this key
    (sent as a bearer token / header) rather than any per-service config,
    so onboarding a new service into the behavioral graph never requires
    a Ghost Protocol config change -- it's discovered from trace topology.
    """
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    label: Mapped[str] = mapped_column(String(255), default="default")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace: Mapped["Workspace"] = relationship(back_populates="api_keys")
