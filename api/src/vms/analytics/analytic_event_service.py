"""Service para AnalyticEvent — Video Search Service."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.analytics.analytic_event_model import AnalyticEvent


class AnalyticEventService:
    """Serviço de busca e gestão de eventos analíticos."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_event(
        self,
        tenant_id: str,
        camera_id: str,
        event_type: str,
        attributes: dict | None = None,
        embedding: list[float] | None = None,
        thumbnail_key: str | None = None,
        segment_key: str | None = None,
        confidence: float | None = None,
        expires_at: datetime | None = None,
        occurred_at: datetime | None = None,
    ) -> AnalyticEvent:
        """Cria evento analítico."""
        event = AnalyticEvent(
            tenant_id=tenant_id,
            camera_id=camera_id,
            event_type=event_type,
            attributes=attributes,
            embedding=embedding,
            thumbnail_key=thumbnail_key,
            segment_key=segment_key,
            confidence=confidence,
            expires_at=expires_at,
            occurred_at=occurred_at or datetime.utcnow(),
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def search_video(
        self,
        tenant_id: str,
        camera_ids: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        event_types: list[str] | None = None,
        confidence_min: float = 0.0,
        attributes: dict[str, str] | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AnalyticEvent], int]:
        """Busca eventos analíticos com filtros."""
        base = select(AnalyticEvent).where(AnalyticEvent.tenant_id == tenant_id)

        if camera_ids:
            base = base.where(AnalyticEvent.camera_id.in_(camera_ids))
        if start:
            base = base.where(AnalyticEvent.occurred_at >= start)
        if end:
            base = base.where(AnalyticEvent.occurred_at <= end)
        if event_types:
            base = base.where(AnalyticEvent.event_type.in_(event_types))
        if confidence_min > 0:
            base = base.where(AnalyticEvent.confidence >= confidence_min)
        if attributes:
            # Filtros JSON: cross-dialect (PostgreSQL JSONB ->> / SQLite json_extract)
            for key, value in attributes.items():
                base = base.where(AnalyticEvent.attributes[key].astext == value)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = await self.db.scalar(count_stmt) or 0

        stmt = (
            base.order_by(AnalyticEvent.occurred_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        result = await self.db.scalars(stmt)
        return list(result.all()), total

    async def search_lpr(
        self,
        tenant_id: str,
        plate: str | None = None,
        camera_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[list[AnalyticEvent], int]:
        """Busca eventos LPR por placa (wildcard ILIKE)."""
        base = select(AnalyticEvent).where(
            AnalyticEvent.tenant_id == tenant_id,
            AnalyticEvent.event_type == "lpr",
        )

        if plate:
            # Wildcard: ABC* → ABC%, *1234 → %1234
            pattern = plate.replace("*", "%")
            base = base.where(AnalyticEvent.attributes["plate"].astext.ilike(pattern))
        if camera_id:
            base = base.where(AnalyticEvent.camera_id == camera_id)
        if start:
            base = base.where(AnalyticEvent.occurred_at >= start)
        if end:
            base = base.where(AnalyticEvent.occurred_at <= end)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = await self.db.scalar(count_stmt) or 0

        stmt = base.order_by(AnalyticEvent.occurred_at.desc()).limit(100)
        result = await self.db.scalars(stmt)
        return list(result.all()), total

    async def get_event_stats(self, tenant_id: str, hours: int = 24) -> dict[str, Any]:
        """Retorna estatísticas agregadas de analytic_events nas últimas X horas."""
        since = datetime.utcnow() - timedelta(hours=hours)
        where = [AnalyticEvent.tenant_id == tenant_id, AnalyticEvent.occurred_at >= since]

        total = await self.db.scalar(select(func.count()).where(*where)) or 0

        type_result = await self.db.execute(
            select(AnalyticEvent.event_type, func.count())
            .where(*where)
            .group_by(AnalyticEvent.event_type)
        )
        by_plugin = {row[0]: row[1] for row in type_result.all()}

        camera_result = await self.db.execute(
            select(AnalyticEvent.camera_id, func.count())
            .where(*where)
            .group_by(AnalyticEvent.camera_id)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_cameras = [
            {"camera_id": row[0], "camera_name": None, "count": row[1]}
            for row in camera_result.all()
        ]

        return {
            "total": total,
            "by_severity": {},
            "by_plugin": by_plugin,
            "top_cameras": top_cameras,
            "period_hours": hours,
        }

    async def cleanup_expired_events(self) -> int:
        """Remove eventos analíticos expirados. Preserva LPR com < 365 dias."""
        from sqlalchemy import delete

        now = datetime.utcnow()
        stmt = delete(AnalyticEvent).where(
            AnalyticEvent.expires_at < now,
            # Nunca deletar LPR antes de 365 dias
            AnalyticEvent.event_type != "lpr",
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount or 0
