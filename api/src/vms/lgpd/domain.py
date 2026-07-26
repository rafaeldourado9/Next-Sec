"""Entidades de domínio de Compliance & LGPD."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from vms.shared.events import DomainEvent
from vms.shared.kernel import AuditId, EntityId, TenantId


class DataType(StrEnum):
    """Tipos de dados sujeitos a retenção."""

    VIDEO = "video"
    ALPR = "alpr"
    FACE = "face"
    AUDIT = "audit"
    ANALYTICS = "analytics"


class ConsentAction(StrEnum):
    """Ações de consentimento."""

    GRANTED = "granted"
    REVOKED = "revoked"


class RequestType(StrEnum):
    """Tipos de solicitação do titular."""

    EXPORT = "export"
    DELETE = "delete"
    ANONYMIZE = "anonymize"


@dataclass(frozen=True)
class ConsentRecorded(DomainEvent):
    """Evento: consentimento LGPD registrado."""
    tenant_id: TenantId | None = None
    data_type: str = ""
    action: str = ""


@dataclass
class ConsentRecord:
    """Registro de consentimento LGPD."""

    id: AuditId
    tenant_id: TenantId
    user_id: EntityId | None = None
    data_type: DataType = DataType.FACE
    action: ConsentAction = ConsentAction.GRANTED
    consent_text_hash: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RetentionPolicy:
    """Política de retenção para um tipo de dado."""

    id: AuditId
    tenant_id: TenantId
    data_type: DataType
    retention_days: int
    anonymize_instead_of_delete: bool = True
    auto_enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def cutoff_date(self) -> datetime:
        """Data limite: dados antes desta data devem ser processados."""
        from datetime import timedelta
        return datetime.utcnow() - timedelta(days=self.retention_days)


@dataclass
class DataSubjectRequest:
    """Solicitação de titular de dados (Art. 18 LGPD)."""

    id: AuditId
    tenant_id: TenantId
    request_type: RequestType
    status: str = "pending"  # pending, processing, completed, rejected
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    result_url: str | None = None
    notes: str | None = None
