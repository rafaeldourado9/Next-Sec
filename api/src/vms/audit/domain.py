"""Entidades de domínio de auditoria."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from vms.shared.events import DomainEvent
from vms.shared.kernel import AggregateRoot, AuditId, EntityId, TenantId


@dataclass(frozen=True)
class AuditLogCreated(DomainEvent):
    """Evento de domínio: log de auditoria foi criado."""
    audit_id: AuditId | None = None
    tenant_id: TenantId | None = None
    action: str = ""
    resource_type: str = ""


@dataclass
class AuditLog(AggregateRoot):
    """
    Log de auditoria — registro imutável de uma ação no sistema.

    Regra de ouro: NUNCA recebe UPDATE ou DELETE. Apenas INSERT.
    Particionamento mensal garante performance com anos de dados.
    """
    id: AuditId = field(default_factory=lambda: AuditId(uuid4()))
    tenant_id: TenantId | None = None
    user_id: EntityId | None = None
    user_email: str | None = None
    user_role: str | None = None
    action: str = ""
    resource_type: str | None = None
    resource_id: EntityId | None = None
    resource_name: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: UUID | None = None
    payload: dict = field(default_factory=dict)
    result: str = "success"  # success | error | denied
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_success(self) -> bool:
        return self.result == "success"

    @property
    def is_error(self) -> bool:
        return self.result in ("error", "denied")
