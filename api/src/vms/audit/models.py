"""Modelos SQLAlchemy para auditoria."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Index, String, Text, TypeDecorator, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from vms.infrastructure.database.connection import Base

_JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


class _SqliteUUIDString(TypeDecorator):
    """SQLite UUID storage with UUID/string bind support."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return str(value) if value is not None else None


_UUID_TYPE = UUID(as_uuid=False).with_variant(_SqliteUUIDString(), "sqlite")


class AuditLogModel(Base):
    """
    Modelo para logs de auditoria.

    Tabela particionada por RANGE(occurred_at) — partições mensais.
    Regra: NUNCA UPDATE ou DELETE nesta tabela.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index('ix_audit_log_tenant_occurred', 'tenant_id', 'occurred_at'),
        Index('ix_audit_log_user_occurred', 'user_id', 'occurred_at'),
        Index('ix_audit_log_action_occurred', 'action', 'occurred_at'),
        Index('ix_audit_log_resource', 'resource_type', 'resource_id'),
    )

    id = Column(_UUID_TYPE, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(_UUID_TYPE, nullable=False)
    user_id = Column(_UUID_TYPE, nullable=True)
    user_email = Column(String(255), nullable=True)
    user_role = Column(String(50), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(_UUID_TYPE, nullable=True)
    resource_name = Column(String(255), nullable=True)
    ip_address = Column(String(45), nullable=True)  # IPv6 max = 45 chars
    user_agent = Column(Text(), nullable=True)
    request_id = Column(_UUID_TYPE, nullable=True)
    payload = Column(_JSON_TYPE, nullable=True, server_default=text("'{}'"))
    result = Column(String(20), nullable=True, server_default=text("'success'"))
    occurred_at = Column(DateTime(timezone=True), nullable=True, server_default=func.now())

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action} resource={self.resource_type}:{self.resource_id}>"
