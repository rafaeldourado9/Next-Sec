"""
Shared Kernel — Tipos base para todos os bounded contexts.

Este módulo define os fundamentos do domínio:
- IDs fortes (evita confusão entre CameraId vs TenantId)
- Entidades (igualdade por identidade)
- Aggregate Roots (colecionam Domain Events)
- Value Objects (imutáveis, igualdade estrutural)
- Domain Events (eventos de passado, imutáveis)
- Repository interfaces (contratos no domínio)
- Exceções de domínio (regras violadas)

REGRA: Este módulo NUNCA importa de outro bounded context.
       Ele define contratos, não implementações.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, TypeVar
from uuid import UUID, uuid4


# ─── IDs Fortes ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EntityId:
    """
    ID forte para entidades — previne confusão entre tipos de ID.

    Uso:
        class CameraId(EntityId): ...
        class TenantId(EntityId): ...

    camera_id == tenant_id  → False (mesmo valor, tipos diferentes)
    """
    value: UUID

    @classmethod
    def new(cls) -> EntityId:
        """Gera novo ID único."""
        return cls(uuid4())

    @classmethod
    def from_string(cls, value: str) -> EntityId:
        """Cria EntityId a partir de string UUID."""
        return cls(UUID(value))

    def __str__(self) -> str:
        return str(self.value)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EntityId):
            return False
        return self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)


# IDs específicos — use estas subclasses, não EntityId direto

class TenantId(EntityId):
    """Identificador de Tenant (multi-tenant)."""
    pass


class CameraId(EntityId):
    """Identificador de Câmera."""
    pass


class UserId(EntityId):
    """Identificador de Usuário."""
    pass


class EventId(EntityId):
    """Identificador de Evento (VmsEvent)."""
    pass


class AuditId(EntityId):
    """Identificador de Log de Auditoria."""
    pass


class RecordingId(EntityId):
    """Identificador de Segmento de Gravação."""
    pass


class VODStreamId(EntityId):
    """Identificador de stream VOD."""
    pass



class PluginId(EntityId):
    """Identificador de Plugin Analytics."""
    pass


class ReportId(EntityId):
    """Identificador de Relatório."""
    pass


class BillingId(EntityId):
    """Identificador de registro de billing."""
    pass


# ─── Entity Base ──────────────────────────────────────────────────────────────

@dataclass
class Entity:
    """
    Entidade base — toda entidade tem identidade e igualdade por ID.

    Uso:
        @dataclass
        class Camera(Entity):
            id: CameraId
            name: str
            ...
    """
    id: EntityId

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id})"


# ─── Aggregate Root ──────────────────────────────────────────────────────────

# (DomainEvent definido abaixo para evitar import circular)


@dataclass
class AggregateRoot(Entity):
    """
    Aggregate Root — entidade principal de um aggregate.

    Coleciona Domain Events que ocorreram dentro do aggregate.
    Após commit, os events são extraídos e publicados.

    Uso:
        class Camera(AggregateRoot):
            def activate(self) -> None:
                self.is_active = True
                self.record_event(CameraActivated(self.id))

        camera = Camera(...)
        camera.activate()
        events = camera.pull_events()  # [CameraActivated(...)]
        await event_bus.publish_many(events)
    """
    _domain_events: list = field(default_factory=list, repr=False, init=False)

    def record_event(self, event: Any) -> None:
        """Registra um Domain Event (será publicado após commit)."""
        self._domain_events.append(event)

    def pull_events(self) -> list:
        """Extrai e limpa os events pendentes (chamar após commit)."""
        events = list(self._domain_events)
        self._domain_events.clear()
        return events

    def clear_events(self) -> None:
        """Limpa events pendentes sem extrair (uso em testes)."""
        self._domain_events.clear()

    @property
    def has_pending_events(self) -> bool:
        """Verifica se há events pendentes."""
        return len(self._domain_events) > 0

    @property
    def pending_events_count(self) -> int:
        """Quantidade de events pendentes."""
        return len(self._domain_events)


# ─── Value Object Base ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class ValueObject:
    """
    Value Object — definido por seus atributos, não por identidade.

    Características:
    - Imutável (frozen=True)
    - Igualdade estrutural (dois VOs com mesmos valores são iguais)
    - Sem identidade (não tem id)

    Uso:
        @dataclass(frozen=True)
        class Coordinates(ValueObject):
            latitude: float
            longitude: float
    """
    pass


# ─── Repository Port (Interface) ─────────────────────────────────────────────

T = TypeVar("T", bound=Entity)


class Repository(Protocol[T]):
    """
    Interface base para repositórios de entidades.

    Implementações ficam em infrastructure/, não no domínio.
    Uso no domínio:
        class CameraRepository(Repository[Camera], Protocol):
            async def find_by_tenant(self, tenant_id: TenantId) -> list[Camera]: ...
    """

    async def get_by_id(self, id: EntityId) -> T | None: ...
    async def add(self, entity: T) -> None: ...
    async def remove(self, entity: T) -> None: ...


# ─── Domain Exceptions (aliases para exceptions.py) ───────────────────────────

# Estes são imports de conveniência para quem quer acessar via shared.kernel
# A definição real está em shared.exceptions

from vms.shared.exceptions import (
    DomainError,
    NotFoundError,
    BusinessRuleViolation,
    UnauthorizedError,
    IntegrityError,
    DuplicateError,
    StateTransitionError,
)

__all__ = [
    # IDs
    "EntityId",
    "TenantId",
    "CameraId",
    "UserId",
    "EventId",
    "AuditId",
    "RecordingId",
    "VODStreamId",
    "PluginId",
    "ReportId",
    "BillingId",
    # Entity
    "Entity",
    # Aggregate Root
    "AggregateRoot",
    # Value Object
    "ValueObject",
    # Repository
    "Repository",
    # Exceptions
    "DomainError",
    "NotFoundError",
    "BusinessRuleViolation",
    "UnauthorizedError",
    "IntegrityError",
    "DuplicateError",
    "StateTransitionError",
]
