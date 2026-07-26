"""Modelos SQLAlchemy ORM para o bounded context IAM."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vms.infrastructure.database import Base

_UUID_TYPE = UUID(as_uuid=False).with_variant(String(36), "sqlite")


def _uuid() -> str:
    return str(uuid.uuid4())


class TenantModel(Base):
    """Tabela de tenants."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    facial_recognition_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    facial_recognition_consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    
    # Billing fields (Sprint 13 — whitelabel license key)
    license_key_id: Mapped[str | None] = mapped_column(_UUID_TYPE, nullable=True)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # White-label branding — aparece nos PDFs de relatório
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cnpj: Mapped[str | None] = mapped_column(String(18), nullable=True)
    company_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Soft delete (Sprint 5 — admin pode arquivar tenant)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    users: Mapped[list["UserModel"]] = relationship("UserModel", back_populates="tenant")


class UserModel(Base):
    """Tabela de usuários."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        _UUID_TYPE, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    tenant: Mapped["TenantModel"] = relationship("TenantModel", back_populates="users")


class ApiKeyModel(Base):
    """Tabela de API keys."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        _UUID_TYPE, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_type: Mapped[str] = mapped_column(String(50), nullable=False)
    owner_id: Mapped[str] = mapped_column(_UUID_TYPE, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
