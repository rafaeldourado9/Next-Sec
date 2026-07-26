"""Modelos SQLAlchemy ORM para o bounded context de eventos."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy import JSON as JSONB  # Compatível com SQLite para testes
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from vms.infrastructure.database import Base

_UUID_TYPE = UUID(as_uuid=False).with_variant(String(36), "sqlite")


def _uuid() -> str:
    """Gera UUID v4 como string."""
    return str(uuid.uuid4())


class VmsEventModel(Base):
    """Tabela de eventos do VMS."""

    __tablename__ = "vms_events"
    __table_args__ = (
        Index("ix_vms_events_tenant_occurred", "tenant_id", "occurred_at"),
        Index("ix_vms_events_plate", "plate"),
    )

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        _UUID_TYPE,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    camera_id: Mapped[str | None] = mapped_column(
        _UUID_TYPE,
        ForeignKey("cameras.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        server_default=func.now(),
    )
