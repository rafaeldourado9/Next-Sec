"""Modelo SQLAlchemy ORM para o bounded context de recordings.

`RecordingWindowModel` NÃO é o índice de segmentos físicos gravados pelo
MediaMTX — é só um índice leve de cobertura ("quais intervalos de tempo têm
gravação"), usado pra sombrear a timeline no frontend. O MediaMTX é quem
grava e apaga os arquivos fMP4 de fato (record/recordDeleteAfter por path).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from vms.infrastructure.database import Base

_UUID_TYPE = UUID(as_uuid=False).with_variant(String(36), "sqlite")


def _uuid() -> str:
    """Gera UUID v4 como string."""
    return str(uuid.uuid4())


class RecordingWindowModel(Base):
    """Sessão contígua de gravação de uma câmera (1 linha por sessão, não por segmento)."""

    __tablename__ = "recording_windows"

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        _UUID_TYPE, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    camera_id: Mapped[str] = mapped_column(
        _UUID_TYPE, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
