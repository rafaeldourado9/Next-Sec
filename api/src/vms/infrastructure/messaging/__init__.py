"""Infrastructure — Messaging (RabbitMQ event bus e DLQ)."""
from vms.infrastructure.messaging.dlq import record_failure
from vms.infrastructure.messaging.event_bus import (
    DomainEventBus,
    EventRegistry,
    connect_event_bus,
    disconnect_event_bus,
    publish_event,
)

__all__ = [
    "DomainEventBus",
    "EventRegistry",
    "publish_event",
    "connect_event_bus",
    "disconnect_event_bus",
    "record_failure",
]
