"""Modelos SQLAlchemy ORM para o bounded context de notificações."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from vms.infrastructure.database import Base

_UUID_TYPE = UUID(as_uuid=False).with_variant(String(36), "sqlite")


def _uuid() -> str:
    """Gera UUID v4 como string."""
    return str(uuid.uuid4())


class NotificationRuleModel(Base):
    """Tabela de regras de notificação por webhook."""

    __tablename__ = "notification_rules"

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        _UUID_TYPE,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type_pattern: Mapped[str] = mapped_column(String(200), nullable=False)
    # ADITIVO (migration 0006): destination_type/contact_id/channel — ver ADR-009
    destination_type: Mapped[str] = mapped_column(String(20), nullable=False, default="webhook")
    destination_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_id: Mapped[str | None] = mapped_column(
        _UUID_TYPE, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="whatsapp")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NotificationLogModel(Base):
    """Tabela de logs de tentativas de dispatch de webhook."""

    __tablename__ = "notification_logs"

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        _UUID_TYPE,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_id: Mapped[str] = mapped_column(
        _UUID_TYPE,
        ForeignKey("notification_rules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vms_event_id: Mapped[str] = mapped_column(
        _UUID_TYPE,
        ForeignKey("vms_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    dispatched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
