"""Ports (interfaces) e implementação SQLAlchemy para recordings."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.recordings.domain import RecordingWindow
from vms.recordings.models import RecordingWindowModel


class RecordingWindowRepositoryPort(Protocol):
    """Interface do repositório de janelas de gravação."""

    async def get_open_window(self, camera_id: str) -> RecordingWindow | None: ...

    async def create(self, window: RecordingWindow) -> RecordingWindow: ...

    async def extend(
        self, window_id: str, ended_at: datetime, segment_count: int
    ) -> RecordingWindow: ...

    async def list_in_range(
        self, camera_id: str, tenant_id: str, start: datetime, end: datetime
    ) -> list[RecordingWindow]: ...

    async def delete_before(self, camera_id: str, cutoff: datetime) -> int: ...


def _to_domain(m: RecordingWindowModel) -> RecordingWindow:
    return RecordingWindow(
        id=m.id,
        tenant_id=m.tenant_id,
        camera_id=m.camera_id,
        started_at=m.started_at,
        ended_at=m.ended_at,
        segment_count=m.segment_count,
    )


class RecordingWindowRepository:
    """Repositório SQLAlchemy para RecordingWindow."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_open_window(self, camera_id: str) -> RecordingWindow | None:
        """Busca a janela ainda aberta (ended_at IS NULL) da câmera, se houver."""
        stmt = select(RecordingWindowModel).where(
            RecordingWindowModel.camera_id == camera_id,
            RecordingWindowModel.ended_at.is_(None),
        )
        result = await self._session.scalar(stmt)
        return _to_domain(result) if result else None

    async def create(self, window: RecordingWindow) -> RecordingWindow:
        """Abre uma nova janela de gravação."""
        model = RecordingWindowModel(
            id=window.id or str(uuid.uuid4()),
            tenant_id=window.tenant_id,
            camera_id=window.camera_id,
            started_at=window.started_at,
            ended_at=window.ended_at,
            segment_count=window.segment_count,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def extend(
        self, window_id: str, ended_at: datetime, segment_count: int
    ) -> RecordingWindow:
        """Estende uma janela existente (novo fim + contagem de segmentos)."""
        model = await self._session.get(RecordingWindowModel, window_id)
        if not model:
            raise ValueError(f"RecordingWindow {window_id} não encontrada")
        model.ended_at = ended_at
        model.segment_count = segment_count
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def list_in_range(
        self, camera_id: str, tenant_id: str, start: datetime, end: datetime
    ) -> list[RecordingWindow]:
        """Lista janelas que se sobrepõem ao intervalo [start, end] pedido."""
        stmt = (
            select(RecordingWindowModel)
            .where(
                RecordingWindowModel.camera_id == camera_id,
                RecordingWindowModel.tenant_id == tenant_id,
                RecordingWindowModel.started_at <= end,
                (
                    RecordingWindowModel.ended_at.is_(None)
                    | (RecordingWindowModel.ended_at >= start)
                ),
            )
            .order_by(RecordingWindowModel.started_at)
        )
        result = await self._session.scalars(stmt)
        return [_to_domain(m) for m in result.all()]

    async def delete_before(self, camera_id: str, cutoff: datetime) -> int:
        """Remove (ou encurta, se cruzar o cutoff) janelas mais antigas que `cutoff`.

        Só apaga janelas totalmente encerradas (ended_at IS NOT NULL e < cutoff)
        — nunca a janela aberta atual, mesmo que started_at seja antigo.
        """
        stmt = delete(RecordingWindowModel).where(
            RecordingWindowModel.camera_id == camera_id,
            RecordingWindowModel.ended_at.is_not(None),
            RecordingWindowModel.ended_at < cutoff,
        )
        result = await self._session.execute(stmt)
        return result.rowcount or 0
