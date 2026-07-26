"""Service de Analytics — gestão de plugins e eventos."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.analytics.models import AnalyticsEvent, PluginInstallation

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Serviço para gestão de plugins de analytics e eventos."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Plugin Installations ─────────────────────────────────────────────

    async def list_installations(self, tenant_id: uuid.UUID) -> list[PluginInstallation]:
        """Lista plugins instalados do tenant.

        NOTA: este método estava corrompido no código herdado (corpo colado
        de `create_event`, referenciava `plugin_id`/`camera_id` inexistentes
        e chamaria `result.scalars()` duas vezes sobre o mesmo resultado —
        daria NameError em qualquer chamada real). Corrigido durante o
        Sprint 2 do Next Sec.
        """
        result = await self.db.execute(
            select(PluginInstallation).where(PluginInstallation.tenant_id == str(tenant_id))
        )
        return list(result.scalars().all())

    async def create_installation(
        self,
        tenant_id: uuid.UUID,
        plugin_id: str,
        plugin_name: str,
        edge_agent_id: str,
        settings: dict | None = None,
    ) -> PluginInstallation:
        """Registra instalação de plugin."""
        installation = PluginInstallation(
            plugin_id=plugin_id,
            plugin_name=plugin_name,
            edge_agent_id=edge_agent_id,
            tenant_id=str(tenant_id),
            settings=settings or {},
        )
        self.db.add(installation)
        await self.db.commit()
        await self.db.refresh(installation)
        logger.info(
            "Plugin %s instalado no edge %s (tenant %s)", plugin_id, edge_agent_id, tenant_id
        )
        return installation

    async def update_installation_status(
        self,
        installation_id: uuid.UUID,
        status: str,
    ) -> PluginInstallation | None:
        """Atualiza status de uma instalação."""
        result = await self.db.execute(
            select(PluginInstallation).where(PluginInstallation.id == str(installation_id))
        )
        installation = result.scalar_one_or_none()
        if not installation:
            return None

        installation.status = status
        await self.db.commit()
        await self.db.refresh(installation)
        return installation

    async def delete_installation(self, installation_id: uuid.UUID) -> bool:
        """Remove instalação de plugin."""
        result = await self.db.execute(
            select(PluginInstallation).where(PluginInstallation.id == str(installation_id))
        )
        installation = result.scalar_one_or_none()
        if not installation:
            return False

        await self.db.delete(installation)
        await self.db.commit()
        return True

    # ─── Analytics Events ─────────────────────────────────────────────────

    async def create_event(
        self,
        tenant_id: uuid.UUID,
        plugin_id: str,
        camera_id: str,
        event_type: str,
        severity: str,
        payload: dict,
        confidence: float | None = None,
        occurred_at: datetime | None = None,
        camera_name: str | None = None,
        snapshot_path: str | None = None,
    ) -> AnalyticsEvent:
        """Cria evento de analytics."""
        # Encontrar instalação do plugin
        result = await self.db.execute(
            select(PluginInstallation)
            .where(
                PluginInstallation.tenant_id == tenant_id,
                PluginInstallation.plugin_id == plugin_id,
            )
            .limit(1)
        )
        installation = result.scalar_one_or_none()

        event = AnalyticsEvent(
            plugin_installation_id=installation.id if installation else None,
            tenant_id=tenant_id,
            plugin_id=plugin_id,
            camera_id=camera_id,
            camera_name=camera_name,
            event_type=event_type,
            severity=severity,
            confidence=confidence,
            payload=payload,
            snapshot_path=snapshot_path,
            occurred_at=occurred_at or datetime.utcnow(),
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def list_events(
        self,
        tenant_id: uuid.UUID,
        camera_id: str | None = None,
        plugin_id: str | None = None,
        severity: str | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AnalyticsEvent]:
        """Lista eventos do tenant com filtros."""
        query = (
            select(AnalyticsEvent)
            .where(AnalyticsEvent.tenant_id == str(tenant_id))
            .order_by(AnalyticsEvent.occurred_at.desc())
            .limit(limit)
            .offset(offset)
        )

        if camera_id:
            query = query.where(AnalyticsEvent.camera_id == camera_id)
        if plugin_id:
            query = query.where(AnalyticsEvent.plugin_id == plugin_id)
        if severity:
            query = query.where(AnalyticsEvent.severity == severity)
        if occurred_after:
            after = occurred_after.replace(tzinfo=None) if occurred_after.tzinfo else occurred_after
            query = query.where(AnalyticsEvent.occurred_at >= after)
        if occurred_before:
            before = (
                occurred_before.replace(tzinfo=None) if occurred_before.tzinfo else occurred_before
            )
            query = query.where(AnalyticsEvent.occurred_at <= before)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_event_stats(
        self,
        tenant_id: uuid.UUID,
        hours: int = 24,
    ) -> dict[str, Any]:
        """Retorna estatísticas de eventos nas últimas X horas."""
        since = datetime.utcnow() - timedelta(hours=hours)

        # Total de eventos
        total_result = await self.db.execute(
            select(func.count(AnalyticsEvent.id)).where(
                AnalyticsEvent.tenant_id == str(tenant_id),
                AnalyticsEvent.occurred_at >= since,
            )
        )
        total = total_result.scalar() or 0

        # Por severidade
        severity_result = await self.db.execute(
            select(AnalyticsEvent.severity, func.count(AnalyticsEvent.id))
            .where(
                AnalyticsEvent.tenant_id == str(tenant_id),
                AnalyticsEvent.occurred_at >= since,
            )
            .group_by(AnalyticsEvent.severity)
        )
        by_severity = {row[0]: row[1] for row in severity_result.all()}

        # Por plugin
        plugin_result = await self.db.execute(
            select(AnalyticsEvent.plugin_id, func.count(AnalyticsEvent.id))
            .where(
                AnalyticsEvent.tenant_id == str(tenant_id),
                AnalyticsEvent.occurred_at >= since,
            )
            .group_by(AnalyticsEvent.plugin_id)
        )
        by_plugin = {row[0]: row[1] for row in plugin_result.all()}

        # Por câmera (top 10)
        camera_result = await self.db.execute(
            select(
                AnalyticsEvent.camera_id, AnalyticsEvent.camera_name, func.count(AnalyticsEvent.id)
            )
            .where(
                AnalyticsEvent.tenant_id == str(tenant_id),
                AnalyticsEvent.occurred_at >= since,
            )
            .group_by(AnalyticsEvent.camera_id, AnalyticsEvent.camera_name)
            .order_by(func.count(AnalyticsEvent.id).desc())
            .limit(10)
        )
        by_camera = [
            {"camera_id": row[0], "camera_name": row[1], "count": row[2]}
            for row in camera_result.all()
        ]

        return {
            "total": total,
            "by_severity": by_severity,
            "by_plugin": by_plugin,
            "top_cameras": by_camera,
            "period_hours": hours,
        }
