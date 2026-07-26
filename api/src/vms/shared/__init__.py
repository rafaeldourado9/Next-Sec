"""
Shared — Shared Kernel do VMS.

Módulo base compartilhado entre todos os bounded contexts.
Define contratos, não implementações.

Componentes:
- kernel: EntityId, Entity, AggregateRoot, ValueObject, Repository
- events: DomainEvent base
- clock: Clock abstraction (RealClock, FakeClock)
- value_objects: Coordinates, IpAddress, TimeRange, Confidence, Sha256Hash
- exceptions: DomainError, NotFoundError, BusinessRuleViolation, etc.

REGRA: Este módulo NUNCA importa de outro bounded context.
"""
from __future__ import annotations

# Kernel (IDs, Entity, Aggregate, ValueObject, Repository)
from vms.shared.kernel import (
    EntityId,
    TenantId,
    CameraId,
    UserId,
    EventId,
    AuditId,
    RecordingId,
    VODStreamId,
    PluginId,
    ReportId,
    BillingId,
    Entity,
    AggregateRoot,
    ValueObject,
    Repository,
    DomainError,
    NotFoundError,
    BusinessRuleViolation,
    UnauthorizedError,
    IntegrityError,
    DuplicateError,
    StateTransitionError,
)

# Domain Events
from vms.shared.events import DomainEvent

# Clock
from vms.shared.clock import Clock, RealClock, FakeClock, clock

# Value Objects
from vms.shared.value_objects import (
    Coordinates,
    IpAddress,
    TimeRange,
    Confidence,
    Sha256Hash,
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
    # Entity/Aggregate
    "Entity",
    "AggregateRoot",
    # Value Object
    "ValueObject",
    # Repository
    "Repository",
    # Domain Events
    "DomainEvent",
    # Clock
    "Clock",
    "RealClock",
    "FakeClock",
    "clock",
    # Value Objects concretos
    "Coordinates",
    "IpAddress",
    "TimeRange",
    "Confidence",
    "Sha256Hash",
    # Exceptions
    "DomainError",
    "NotFoundError",
    "BusinessRuleViolation",
    "UnauthorizedError",
    "IntegrityError",
    "DuplicateError",
    "StateTransitionError",
]
