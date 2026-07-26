"""
Ports do Bounded Context: Events.

Interfaces que o Events Context exporta para outros contexts usarem.
"""
from __future__ import annotations

from typing import Protocol


class EventIngestionPort(Protocol):
    """
    Porta para ingerir eventos no Events Context.

    Outros contexts (como Plugins) publicam eventos via esta porta
    ao invés de escrever diretamente na tabela VmsEventModel.

    Implementação real: EventService do bounded context Events.
    """

    async def ingest_event(
        self,
        tenant_id: str,
        event_type: str,
        payload: dict,
        camera_id: str | None = None,
        plate: str | None = None,
        confidence: float | None = None,
    ) -> str:
        """Ingere evento e retorna o ID do evento criado."""
        ...
