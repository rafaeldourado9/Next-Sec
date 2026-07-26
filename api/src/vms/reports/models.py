"""Modelos SQLAlchemy para relatórios."""
from __future__ import annotations

import uuid
from datetime import datetime

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


class ReportModel(Base):
    """Tabela de relatórios gerados."""

    __tablename__ = "reports"
    __table_args__ = (
        Index('ix_reports_tenant_created', 'tenant_id', 'created_at'),
        Index('ix_reports_status', 'status'),
    )

    id = Column(_UUID_TYPE, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(_UUID_TYPE, nullable=False)
    report_type = Column(String(50), nullable=False)
    parameters = Column(_JSON_TYPE, nullable=False, server_default=text("'{}'"))
    status = Column(String(20), nullable=False, server_default=text("'pending'"))
    file_path = Column(String(1000), nullable=True)
    sha256_hash = Column(String(64), nullable=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    generated_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(_UUID_TYPE, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __init__(self, **kwargs) -> None:
        kwargs.pop("name", None)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self) -> str:
        return f"<Report id={self.id} type={self.report_type} status={self.status}>"
