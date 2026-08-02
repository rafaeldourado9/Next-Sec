"""Modelos SQLAlchemy ORM para o bounded context de eventos."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, func, text
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
        # Idempotência do ingest em lote (ADR-018 §5): o edge reenvia o que não
        # teve resposta confirmada, então o mesmo evento pode chegar duas vezes.
        # Único por tenant, não global — o ID é gerado no cliente.
        Index(
            "uq_vms_events_tenant_client_event",
            "tenant_id",
            "client_event_id",
            unique=True,
            postgresql_where=text("client_event_id IS NOT NULL"),
        ),
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
    # UUID gerado no edge — chave de idempotência do ingest em lote (ADR-018
    # §5). Nulo para eventos de origem não-edge (webhooks, Nível 3).
    client_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        server_default=func.now(),
    )


class RawCameraEventModel(Base):
    """Ledger imutável do payload bruto recebido de webhooks de câmera
    (Hikvision/Intelbras ANPR). Nunca é UPDATE'd exceto para linkar
    `vms_event_id` depois que o normalizer processa o payload -- o corpo
    capturado em si nunca muda. Existe pra permitir reprocessar/auditar
    detecções (ex: campo de confiança) sem depender da câmera reenviar o
    evento, já que o normalizer historicamente descartava o payload
    original ao extrair só os campos já conhecidos."""

    __tablename__ = "raw_camera_events"
    __table_args__ = (
        Index("ix_raw_camera_events_tenant_received", "tenant_id", "received_at"),
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
    vms_event_id: Mapped[str | None] = mapped_column(
        _UUID_TYPE,
        ForeignKey("vms_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    manufacturer: Mapped[str] = mapped_column(String(50), nullable=False)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        server_default=func.now(),
    )
