"""Ports (interfaces) e implementação SQLAlchemy para event_clips."""
from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.event_clips.domain import ClipStatus, EventClip
from vms.event_clips.models import EventClipModel


class EventClipRepositoryPort(Protocol):
    """Interface do repositório de clipes de evento."""

    async def get_by_event(self, vms_event_id: str) -> EventClip | None: ...

    async def create(self, clip: EventClip) -> EventClip: ...

    async def update_status(
        self, clip_id: str, status: ClipStatus, **fields: object
    ) -> EventClip: ...


def _to_domain(m: EventClipModel) -> EventClip:
    """Converte modelo ORM para entidade de domínio."""
    return EventClip(
        id=m.id,
        vms_event_id=m.vms_event_id,
        tenant_id=m.tenant_id,
        size_bytes=m.size_bytes or 0,
        storage_provider=m.storage_provider,
        storage_ref=m.storage_ref,
        storage_url=m.storage_url,
        status=ClipStatus(m.status),
        duration_seconds=m.duration_seconds,
        error_message=m.error_message,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


class EventClipRepository:
    """Repositório SQLAlchemy para EventClip."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_event(self, vms_event_id: str) -> EventClip | None:
        """Busca o clipe de um evento, se já existir."""
        stmt = select(EventClipModel).where(EventClipModel.vms_event_id == vms_event_id)
        result = await self._session.scalar(stmt)
        return _to_domain(result) if result else None

    async def get_by_id(self, clip_id: str) -> EventClip | None:
        """Busca clipe por ID."""
        result = await self._session.get(EventClipModel, clip_id)
        return _to_domain(result) if result else None

    async def create(self, clip: EventClip) -> EventClip:
        """Cria o registro inicial do clipe (status=pending)."""
        model = EventClipModel(
            id=clip.id or str(uuid.uuid4()),
            vms_event_id=clip.vms_event_id,
            tenant_id=clip.tenant_id,
            size_bytes=clip.size_bytes,
            storage_provider=clip.storage_provider,
            status=clip.status.value,
            duration_seconds=clip.duration_seconds,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def update_status(
        self, clip_id: str, status: ClipStatus, **fields: object
    ) -> EventClip:
        """Atualiza status e campos adicionais (storage_ref, storage_url, error_message)."""
        model = await self._session.get(EventClipModel, clip_id)
        if not model:
            raise ValueError(f"EventClip {clip_id} não encontrado")
        model.status = status.value
        for key, value in fields.items():
            setattr(model, key, value)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)
