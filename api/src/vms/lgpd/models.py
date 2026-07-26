"""Modelos SQLAlchemy para Compliance & LGPD."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, TypeDecorator, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from vms.infrastructure.database.connection import Base


class _SqliteUUIDString(TypeDecorator):
    """SQLite UUID storage with UUID/string bind support."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return str(value) if value is not None else None


_UUID_TYPE = UUID(as_uuid=True).with_variant(_SqliteUUIDString(), "sqlite")


class RetentionPolicyModel(Base):
    """Tabela de políticas de retenção por tipo de dado."""

    __tablename__ = "retention_policies"
    __table_args__ = (
        UniqueConstraint('tenant_id', 'data_type', name='uq_retention_policy'),
    )

    id = Column(_UUID_TYPE, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(_UUID_TYPE, nullable=False)
    data_type = Column(String(50), nullable=False)
    retention_days = Column(Integer(), nullable=False)
    anonymize_instead_of_delete = Column(Boolean(), nullable=False, server_default=text("true"))
    auto_enabled = Column(Boolean(), nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=datetime.utcnow)


class ConsentRecordModel(Base):
    """Tabela de registros de consentimento."""

    __tablename__ = "consent_records"

    id = Column(_UUID_TYPE, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(_UUID_TYPE, nullable=False)
    user_id = Column(_UUID_TYPE, nullable=True)
    data_type = Column(String(50), nullable=False)
    action = Column(String(20), nullable=False)
    consent_text_hash = Column(String(64), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text(), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
