"""Modelo AnalyticEvent para Video Search Service (tabela analytic_events)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from vms.infrastructure.database import Base

_JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")
_UUID_TYPE = UUID(as_uuid=False).with_variant(String(36), "sqlite")


def _uuid() -> str:
    """Gera UUID v4 como string."""
    return str(uuid.uuid4())


class AnalyticEvent(Base):
    """Tabela central de eventos analíticos para busca de vídeo."""

    __tablename__ = "analytic_events"

    __table_args__ = (
        Index("ix_ae_tenant_camera_occurred", "tenant_id", "camera_id", "occurred_at"),
        Index("ix_ae_event_type_occurred", "event_type", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        _UUID_TYPE,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    camera_id: Mapped[str] = mapped_column(
        _UUID_TYPE,
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # motion | person | vehicle | lpr | face
    attributes: Mapped[dict | None] = mapped_column(_JSON_TYPE, nullable=True)
    # pgvector embedding (512-dim) para face recognition — null para outros tipos
    # Usa String para compatibilidade com SQLite em testes; ivfflat em PostgreSQL
    embedding: Mapped[list[float] | None] = mapped_column(
        _JSON_TYPE, nullable=True
    )  # armazenado como JSONB array no PostgreSQL
    thumbnail_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    segment_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @staticmethod
    def calculate_expires_at(camera_type: str) -> datetime:
        """Calcula data de expiração com base no tipo de câmera."""
        days = {
            "lpr": 365,
            "facial": 7,
            "internal": 7,
            "external": 7,
        }
        return datetime.now(timezone.utc) + timedelta(days=days.get(camera_type, 7))
