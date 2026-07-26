"""
Exemplo de registro de Domain Events e handlers.

Este arquivo demonstra como:
1. Registrar Domain Events no EventRegistry
2. Subscrever handlers para tipos de eventos
3. Publicar eventos após commit

DEVE ser chamado no lifespan da aplicação (main.py).
"""
from __future__ import annotations

import logging

from vms.cameras.domain import (
    CameraActivated,
    CameraAnalyticsDisabled,
    CameraAnalyticsEnableded,
    CameraCreated,
    CameraDeactivated,
)
from vms.infrastructure.messaging.event_bus import DomainEventBus, EventRegistry
from vms.shared.events import DomainEvent

# NOTA (Next Sec): os eventos de recording (SegmentIndexed, ClipRequested,
# ClipReady, ClipFailed) vinham de `vms.recordings.domain`, não copiado
# (gravação contínua fora de escopo — ver reuse-plan.md). O conceito de
# "clipe" do Next Sec é outro (event_clips — clipe de 5-10s de um evento de
# analytics, não segmento de gravação contínua) e ainda precisa de seus
# próprios Domain Events; não reaproveitar os nomes antigos sem revisar.

logger = logging.getLogger(__name__)


def register_all_events(registry: EventRegistry) -> None:
    """
    Registra todos os Domain Events no registry.

    Deve ser chamado uma vez no startup da aplicação.
    """
    # Camera events
    registry.register("CameraCreated", CameraCreated)
    registry.register("CameraActivated", CameraActivated)
    registry.register("CameraDeactivated", CameraDeactivated)
    registry.register("CameraAnalyticsEnableded", CameraAnalyticsEnableded)
    registry.register("CameraAnalyticsDisabled", CameraAnalyticsDisabled)

    # TODO (Next Sec, gap real — ver reuse-plan.md): registrar aqui os
    # Domain Events do fluxo evento→clipe (ex: EventClipUploaded,
    # EventClipFailed) quando o StorageProvider/ChannelAdapter forem
    # implementados.

    logger.info("✅ %d Domain Events registrados", len(registry._event_types))


async def subscribe_all_handlers(bus: DomainEventBus | None) -> None:
    """
    Subscreve todos os handlers de eventos.

    Deve ser chamado uma vez no startup da aplicação.
    Se bus for None, usa o event_bus global.
    """
    from vms.infrastructure.messaging.event_bus import event_bus as global_bus

    target_bus = bus or global_bus
    if target_bus is None:
        logger.warning("Event bus não disponível para subscrever handlers")
        return

    # Exemplo: handler para CameraActivated
    async def on_camera_activated(event: CameraActivated) -> None:
        logger.info(
            "Câmera ativou: camera_id=%s tenant_id=%s",
            event.camera_id,
            event.tenant_id,
        )
        # Aqui poderia:
        # - Publicar notificação SSE
        # - Atualizar cache
        # - Disparar webhook

    # Subscrever handlers
    target_bus.subscribe("CameraActivated", on_camera_activated)

    logger.info("✅ %d handlers de eventos subscritos", target_bus.handler_count)
