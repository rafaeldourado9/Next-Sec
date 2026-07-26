"""Entidades de domínio de contatos (telefones que recebem alertas)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Contact:
    """Telefone cadastrado pelo cliente final para receber alertas de eventos.

    `camera_id=None` significa que o contato recebe alertas de todas as
    câmeras do tenant (confirmado no intake do manifest).
    """

    id: str
    tenant_id: str
    phone_number: str
    name: str
    camera_id: str | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None

    @property
    def is_deleted(self) -> bool:
        """Retorna True se o contato foi removido (soft delete)."""
        return self.deleted_at is not None
