"""
Event Bus — Barramento de eventos de domínio via Redis pub/sub.

Responsabilidade:
    Publicar Domain Events para todos os bounded contexts interessados.
    Subscrever handlers locais a tipos específicos de eventos.
    Reconstruir Domain Events a partir de payloads serializados.

Atores:
    - Publisher: publica eventos de um aggregate (após commit)
    - Subscriber: registra handlers para tipos de eventos
    - Event Registry: mapeia event_type → classe de DomainEvent

Integrações:
    - Todos os bounded contexts publicam e consomem eventos
    - Redis é o transporte (pub/sub)
    - Eventual consistency (não síncrono entre contexts)

Regras de Negócio:
    1. Eventos são publicados APÓS commit no banco
    2. Handlers locais são executados no order de registro
    3. Falhas em handlers são logadas mas não propagam exceções
    4. Eventos são serializados para JSON (Redis pub/sub)

Não faz:
    - Garantia de entrega (fire-and-forget)
    - Ordering entre eventos diferentes
    - Retry automático de handlers falhos (usar DLQ)
"""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from vms.shared.events import DomainEvent

logger = logging.getLogger(__name__)

# Handler: recebe DomainEvent e processa assincronamente
EventHandler = Callable[[DomainEvent], Awaitable[None]]


class EventRegistry:
    """
    Registry de Domain Events — reconstrói eventos a partir de dict.

    Uso:
        registry = EventRegistry()
        registry.register("CameraActivated", CameraActivated)
        registry.register("ClipReady", ClipReady)

        event = registry.reconstruct(payload_dict)
    """

    def __init__(self) -> None:
        self._event_types: dict[str, type[DomainEvent]] = {}

    def register(self, event_type: str, event_class: type[DomainEvent]) -> None:
        """Registra um tipo de evento para reconstrução."""
        self._event_types[event_type] = event_class

    def reconstruct(self, data: dict[str, Any]) -> DomainEvent | None:
        """
        Reconstrói Domain Event a partir de dict serializado.

        Retorna None se event_type não está registrado.
        """
        event_type = data.get("event_type")
        if not event_type:
            logger.warning("Evento sem event_type: %s", data)
            return None

        event_class = self._event_types.get(event_type)
        if not event_class:
            logger.debug("Event type não registrado: %s", event_type)
            return None

        try:
            return event_class.from_dict(data)
        except Exception:
            logger.exception(
                "Falha ao reconstruir evento %s",
                event_type,
                extra={"data": data},
            )
            return None


class DomainEventBus:
    """
    Barramento de eventos de domínio.

    Publica eventos no Redis pub/sub e dispatch para handlers locais.

    Uso:
        bus = DomainEventBus(redis_client)

        # Registrar handlers locais
        bus.subscribe("CameraActivated", handle_camera_activated)
        bus.subscribe("ClipReady", handle_clip_ready)

        # Publicar evento
        await bus.publish(camera_activated_event)
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        registry: EventRegistry | None = None,
    ) -> None:
        self._redis = redis
        self._registry = registry or EventRegistry()
        self._handlers: dict[str, list[EventHandler]] = {}
        self._pubsub: aioredis.client.PubSub | None = None
        self._listening = False

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        Registra handler para tipo de evento.

        Handlers são executados na order de registro.
        Se handler falhar, erro é logado mas não propaga.
        """
        self._handlers.setdefault(event_type, []).append(handler)
        logger.debug("Handler registrado: %s → %s", event_type, handler.__name__)

    async def publish(self, event: DomainEvent) -> None:
        """
        Publica evento para todos os bounded contexts interessados.

        1. Serializa evento para JSON
        2. Publica no Redis pub/sub (channel: "domain_events")
        3. Dispatch para handlers locais
        """
        try:
            # Publica no Redis
            payload = json.dumps(event.to_dict(), default=str)
            await self._redis.publish("domain_events", payload)

            # Dispatch local
            await self._dispatch_locally(event)

            logger.debug(
                "Evento publicado: %s",
                event.event_type,
                extra={"event_type": event.event_type},
            )

        except Exception:
            logger.exception(
                "Falha ao publicar evento %s",
                event.event_type,
                extra={"event_type": event.event_type},
            )

    async def publish_many(self, events: list[DomainEvent]) -> None:
        """Publica múltiplos eventos em sequência."""
        for event in events:
            await self.publish(event)

    async def _dispatch_locally(self, event: DomainEvent) -> None:
        """Dispatch evento para handlers locais."""
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    "Erro ao processar evento %s",
                    event.event_type,
                    extra={
                        "event_type": event.event_type,
                        "handler": handler.__name__,
                    },
                )

    async def start_listening(self) -> None:
        """
        Inicia listener de Redis pub/sub (background task).

        Deve ser chamado como background task no lifespan da app.
        Eventos recebidos são reconstruídos e dispatched localmente.
        """
        if self._listening:
            logger.warning("Event bus já está listening")
            return

        self._listening = True
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe("domain_events")

        logger.info("Event bus listening on channel: domain_events")

        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue

                try:
                    data = json.loads(message["data"])
                    event = self._registry.reconstruct(data)
                    if event:
                        await self._dispatch_locally(event)
                except json.JSONDecodeError:
                    logger.warning(
                        "Mensagem inválida recebida: %s",
                        message["data"][:200],
                    )
                except Exception:
                    logger.exception("Erro ao processar mensagem do Redis")

        except Exception:
            logger.exception("Erro no listener do Redis pub/sub")
        finally:
            self._listening = False
            if self._pubsub:
                await self._pubsub.unsubscribe("domain_events")
                await self._pubsub.close()

    async def stop_listening(self) -> None:
        """Para o listener de Redis pub/sub."""
        self._listening = False
        if self._pubsub:
            await self._pubsub.unsubscribe("domain_events")
            await self._pubsub.close()
            logger.info("Event bus stopped")

    @property
    def is_listening(self) -> bool:
        """Verifica se event bus está listening."""
        return self._listening

    @property
    def handler_count(self) -> int:
        """Total de handlers registrados."""
        return sum(len(handlers) for handlers in self._handlers.values())


# Instância global (injetada via DI)
event_bus: DomainEventBus | None = None
event_registry = EventRegistry()


# ─── Compatibilidade (funções standalone para código legado) ─────────────────

async def publish_event(
    routing_key: str,
    payload: dict,
    *,
    tenant_id: str | None = None,
) -> None:
    """
    Publica evento via Event Bus global (compatibilidade com código legado).

    Além de publicar no canal 'domain_events', também publica em 'sse:{tenant_id}'
    para que o SSE receba o evento no frontend.

    Uso legado:
        from vms.infrastructure.messaging import publish_event
        await publish_event("alpr.detected", {...}, tenant_id="tid")

    Nova forma recomendada:
        await event_bus.publish(domain_event)
    """
    if event_bus is None:
        logger.warning("Event bus não inicializado. Evento descartado: %s", routing_key)
        return

    # Cria DomainEvent genérico para compatibilidade
    from dataclasses import dataclass, field
    from vms.shared.events import DomainEvent

    _routing_key = routing_key
    _payload = payload
    _tenant_id = tenant_id

    @dataclass(frozen=True, kw_only=True)
    class GenericDomainEvent(DomainEvent):
        event_type: str = field(default=_routing_key)
        payload: dict = field(default_factory=lambda: _payload)
        tenant_id: str | None = field(default=_tenant_id)

    event = GenericDomainEvent()
    await event_bus.publish(event)

    # Bridge para SSE: publica no canal tenant-specific
    if tenant_id:
        try:
            sse_message = json.dumps({"event": routing_key, "data": payload}, default=str)
            await event_bus._redis.publish(f"sse:{tenant_id}", sse_message)
        except Exception:
            logger.exception("Falha ao publicar SSE para tenant %s", tenant_id)


async def connect_event_bus() -> None:
    """
    Inicializa o Event Bus global.

    Compatibilidade com código que chama connect_event_bus() no lifespan.
    """
    global event_bus
    from vms.infrastructure.config import get_settings
    import redis.asyncio as aioredis

    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    event_bus = DomainEventBus(redis, event_registry)
    logger.info("Event bus conectado")


async def disconnect_event_bus() -> None:
    """
    Desconecta o Event Bus global.

    Compatibilidade com código que chama disconnect_event_bus() no shutdown.
    """
    global event_bus
    if event_bus:
        await event_bus.stop_listening()
        event_bus = None
        logger.info("Event bus desconectado")
