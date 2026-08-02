"""Modelo SQLAlchemy ORM para o bounded context de event_clips."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from vms.infrastructure.database import Base

_UUID_TYPE = UUID(as_uuid=False).with_variant(String(36), "sqlite")


def _uuid() -> str:
    """Gera UUID v4 como string."""
    return str(uuid.uuid4())


class EventClipModel(Base):
    """Tabela de clipes gerados a partir de um evento (vms_events)."""

    __tablename__ = "event_clips"
    __table_args__ = (Index("ix_event_clips_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=_uuid)
    vms_event_id: Mapped[str] = mapped_column(
        _UUID_TYPE, ForeignKey("vms_events.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Denormalizado de `vms_events.tenant_id` (ADR-018 §4): o clipe nunca muda
    # de dono, e sem isso a cota de storage exigiria um JOIN a cada upload.
    tenant_id: Mapped[str | None] = mapped_column(_UUID_TYPE, nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="local")
    storage_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storage_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
