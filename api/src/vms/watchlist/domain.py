"""Entidades de domínio da watchlist de reconhecimento facial."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class FaceProfile:
    """Rosto cadastrado na watchlist de um tenant.

    O embedding em si é computado e cacheado pelo serviço `analytics/`
    (ver ADR-010/ADR-014) — aqui só guardamos a imagem de referência.
    """

    id: str
    tenant_id: str
    name: str
    reference_image_path: str | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None

    @property
    def is_deleted(self) -> bool:
        """Retorna True se o perfil foi removido (soft delete — direito ao apagamento LGPD)."""
        return self.deleted_at is not None
