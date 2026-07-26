"""
Domain Events — eventos de domínio imutáveis.

Domain Events representam algo que aconteceu no passado.
São imutáveis por definição e usados para comunicação entre bounded contexts.

Uso:
    @dataclass(frozen=True)
    class CameraCreated(DomainEvent):
        camera_id: CameraId
        tenant_id: TenantId
        name: str

    # Emitir:
    event = CameraCreated(camera_id=..., tenant_id=..., name="Camera 01")
    await event_bus.publish(event)

    # Consumir:
    event_bus.subscribe("CameraCreated", handle_camera_created)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """
    Domain Event — algo que aconteceu no passado.

    Características:
    - Imutável (frozen=True)
    - Tem timestamp de ocorrência
    - Nome derivado da classe (CameraCreated, UserLoggedIn, etc.)
    - Serializável para dict (para pub/sub Redis)

    REGRA: Domain Events não devem ser modificados após criação.
           Eles representam fatos históricos.
    """
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def event_type(self) -> str:
        """
        Nome do evento: 'CameraCreated', 'AuditLogCreated', etc.

        Usado como chave no Redis pub/sub para routing.
        """
        return self.__class__.__name__

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dict (para pub/sub, logging, etc.)."""
        data = asdict(self)
        data["event_type"] = self.event_type
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        """
        Reconstrói evento a partir de dict.

        Nota: Em produção, usar um EventRegistry para reconstruir
        o tipo correto baseado em event_type.
        """
        data.pop("event_type", None)
        occurred_at = data.pop("occurred_at", None)
        if occurred_at and isinstance(occurred_at, str):
            from datetime import datetime as dt
            data["occurred_at"] = dt.fromisoformat(occurred_at)
        return cls(**data)

    def __repr__(self) -> str:
        return f"{self.event_type}(occurred_at={self.occurred_at})"
