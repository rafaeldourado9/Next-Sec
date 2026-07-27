"""Casos de uso do bounded context de eventos VMS."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from redis.asyncio import Redis

from vms.infrastructure.config import get_settings
from vms.infrastructure.messaging.event_bus import publish_event
from vms.shared.exceptions import NotFoundError
from vms.events.domain import AlprDetection, VmsEvent
from vms.events.images import save_event_image
from vms.events.repository import EventRepositoryPort

logger = logging.getLogger(__name__)

_DEDUP_KEY_PREFIX = "alpr:dedup"


def _numeric_setting(value, default):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


class EventService:
    """Casos de uso de ingestão e consulta de eventos."""

    def __init__(self, event_repo: EventRepositoryPort) -> None:
        self._events = event_repo

    async def ingest_alpr(
        self,
        detection: AlprDetection,
        redis_client: Redis,
    ) -> VmsEvent | None:
        """
        Ingere detecção ALPR com deduplicação Redis.

        Retorna None se a detecção for duplicata dentro do TTL configurado.
        Publica 'alpr.detected' no event bus se aceita.
        """
        settings = get_settings()
        min_confidence = float(_numeric_setting(getattr(settings, "alpr_min_confidence", None), 0.80))

        # Filtro de confiança mínima — evita poluir o histórico com leituras
        # fracas de placa (OCR parcial, ângulo ruim, borrado).
        if detection.confidence < min_confidence:
            logger.debug(
                "ALPR abaixo do mínimo de confiança: placa=%s conf=%.2f min=%.2f",
                detection.plate,
                detection.confidence,
                min_confidence,
            )
            return None

        # Chave 1 — dedup por timestamp exato (24h TTL): mesmo evento nunca salvo 2x
        exact_ttl = int(_numeric_setting(getattr(settings, "alpr_exact_dedup_ttl_seconds", None), 0))
        if exact_ttl > 0:
            ts_bucket = detection.timestamp.strftime("%Y%m%d%H%M")
            exact_key = f"{_DEDUP_KEY_PREFIX}:exact:{detection.camera_id}:{detection.plate}:{ts_bucket}"
            is_new = await redis_client.set(exact_key, "1", ex=exact_ttl, nx=True)
            if not is_new:
                logger.debug(
                    "ALPR duplicata exata ignorada: placa=%s camera=%s ts=%s",
                    detection.plate,
                    detection.camera_id,
                    ts_bucket,
                )
                return None

        # Chave 2 — dedup por janela TTL: mesma placa na mesma câmera dentro do TTL
        dedup_key = f"{_DEDUP_KEY_PREFIX}:{detection.camera_id}:{detection.plate}"
        ttl = int(_numeric_setting(getattr(settings, "alpr_dedup_ttl_seconds", None), 60))
        is_new = await redis_client.set(dedup_key, "1", ex=ttl, nx=True)
        if not is_new:
            logger.debug(
                "ALPR duplicata ignorada: placa=%s camera=%s",
                detection.plate,
                detection.camera_id,
            )
            return None

        # Salva imagem em disco se disponível
        image_path = save_event_image(
            tenant_id=detection.tenant_id,
            event_id=str(uuid.uuid4()),
            image_b64=detection.image_b64,
            occurred_at=detection.timestamp,
        )

        event = VmsEvent(
            id=str(uuid.uuid4()),
            tenant_id=detection.tenant_id,
            event_type="alpr_detected",
            payload={
                "plate": detection.plate,
                "confidence": detection.confidence,
                "manufacturer": detection.manufacturer,
                "image_b64": detection.image_b64,
                "bbox": detection.bbox,
                "bbox_unit": "pixel" if detection.bbox else None,
                "raw": detection.raw_payload,
            },
            camera_id=detection.camera_id,
            plate=detection.plate,
            confidence=detection.confidence,
            image_path=image_path,
            occurred_at=detection.timestamp,
        )
        saved = await self._events.create(event)

        await publish_event(
            "alpr.detected",
            {
                "event_id": saved.id,
                "camera_id": saved.camera_id,
                "plate": saved.plate,
                "confidence": saved.confidence,
            },
            tenant_id=saved.tenant_id,
        )
        return saved

    async def list_events(
        self,
        tenant_id: str,
        event_type: str | None = None,
        plate: str | None = None,
        camera_id: str | None = None,
        source: str | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
        confidence_min: float | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[VmsEvent], int]:
        """Lista eventos com filtros opcionais. Retorna (items, total)."""
        return await self._events.list_by_tenant(
            tenant_id,
            event_type=event_type,
            plate=plate,
            camera_id=camera_id,
            source=source,
            occurred_after=occurred_after,
            occurred_before=occurred_before,
            confidence_min=confidence_min,
            limit=limit,
            offset=offset,
        )

    async def get_event(self, event_id: str, tenant_id: str) -> VmsEvent:
        """Retorna evento por ID. Lança NotFoundError se não encontrado."""
        event = await self._events.get_by_id(event_id, tenant_id)
        if not event:
            raise NotFoundError("Evento", event_id)
        return event
