"""Ports (interfaces) e implementações SQLAlchemy para eventos."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.events.domain import VmsEvent
from vms.events.models import VmsEventModel

# Tipos de evento que chegam via webhook de câmera (Fluxo A)
_LPR_TYPES = ["alpr_detected", "intelbras_event", "hikvision_motion", "camera_event"]


# ─── Port (interface) ─────────────────────────────────────────────────────────

class EventRepositoryPort(Protocol):
    """Interface do repositório de eventos."""

    async def create(self, event: VmsEvent) -> VmsEvent: ...

    async def list_by_tenant(
        self,
        tenant_id: str,
        event_type: str | None = None,
        plate: str | None = None,
        camera_id: str | None = None,
        source: str | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[VmsEvent], int]: ...

    async def get_by_id(self, event_id: str, tenant_id: str) -> VmsEvent | None: ...


# ─── Conversor ORM ↔ Domain ───────────────────────────────────────────────────

def _event_to_domain(m: VmsEventModel) -> VmsEvent:
    """Converte modelo ORM para entidade de domínio VmsEvent."""
    return VmsEvent(
        id=m.id,
        tenant_id=m.tenant_id,
        event_type=m.event_type,
        payload=m.payload,
        camera_id=m.camera_id,
        plate=m.plate,
        confidence=m.confidence,
        image_path=m.image_path,
        occurred_at=m.occurred_at,
    )


# ─── Implementação SQLAlchemy ─────────────────────────────────────────────────

class EventRepository:
    """Repositório SQLAlchemy para VmsEvent."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, event: VmsEvent) -> VmsEvent:
        """Persiste novo evento."""
        model = VmsEventModel(
            id=event.id,
            tenant_id=event.tenant_id,
            event_type=event.event_type,
            payload=event.payload,
            camera_id=event.camera_id,
            plate=event.plate,
            confidence=event.confidence,
            image_path=event.image_path,
            occurred_at=event.occurred_at,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _event_to_domain(model)

    async def list_by_tenant(
        self,
        tenant_id: str,
        event_type: str | None = None,
        plate: str | None = None,
        camera_id: str | None = None,
        source: str | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[VmsEvent], int]:
        """Lista eventos do tenant com filtros opcionais. Retorna (items, total)."""
        base = select(VmsEventModel).where(VmsEventModel.tenant_id == tenant_id)
        if event_type:
            base = base.where(VmsEventModel.event_type == event_type)
        if plate:
            base = base.where(VmsEventModel.plate == plate.upper())
        if camera_id:
            base = base.where(VmsEventModel.camera_id == camera_id)
        if source == "lpr":
            base = base.where(VmsEventModel.event_type.in_(_LPR_TYPES))
        elif source == "analytics":
            base = base.where(VmsEventModel.event_type.notin_(_LPR_TYPES))
        if occurred_after:
            base = base.where(VmsEventModel.occurred_at >= occurred_after)
        if occurred_before:
            base = base.where(VmsEventModel.occurred_at <= occurred_before)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = await self._session.scalar(count_stmt) or 0

        stmt = base.order_by(VmsEventModel.occurred_at.desc()).limit(limit).offset(offset)
        result = await self._session.scalars(stmt)
        items = [_event_to_domain(m) for m in result.all()]
        return items, total

    async def get_by_id(self, event_id: str, tenant_id: str) -> VmsEvent | None:
        """Busca evento por ID dentro do tenant."""
        stmt = select(VmsEventModel).where(
            VmsEventModel.id == event_id,
            VmsEventModel.tenant_id == tenant_id,
        )
        result = await self._session.scalar(stmt)
        return _event_to_domain(result) if result else None
