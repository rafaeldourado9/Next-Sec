"""
⚠️ DEPRECATED: vms.core.event_bus foi movido para vms.infrastructure.messaging.event_bus

Este módulo existe apenas para compatibilidade durante a migração.
Todos os imports devem ser atualizados para:
    from vms.infrastructure.messaging import connect_event_bus, publish_event, ...

Este arquivo será removido na Sprint A3.
"""
# Compatibilidade — redireciona para novo local
from vms.infrastructure.messaging.event_bus import (  # noqa: F401
    connect_event_bus,
    disconnect_event_bus,
    publish_event,
)

__all__ = [
    "connect_event_bus",
    "disconnect_event_bus",
    "publish_event",
]
