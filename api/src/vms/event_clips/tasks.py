"""Tarefa ARQ de limpeza de clipes antigos (retenção — ver ADR-010 revisado).

Disco da VPS é compartilhado (ADR-005) — clipes acumulados sem limite
esgotariam os 96GB disponíveis. Roda diariamente, remove do storage e do
banco os clipes mais antigos que CLIP_RETENTION_DAYS.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from vms.event_clips.models import EventClipModel
from vms.infrastructure.config import get_settings
from vms.infrastructure.database import get_session_factory
from vms.infrastructure.storage_provider import build_storage_provider

logger = logging.getLogger(__name__)


async def task_cleanup_old_clips(ctx: dict) -> None:
    """Remove clipes com `created_at` mais antigo que `CLIP_RETENTION_DAYS`."""
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=settings.clip_retention_days)
    storage = build_storage_provider()

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(EventClipModel).where(
                EventClipModel.created_at < cutoff,
                EventClipModel.status == "uploaded",
            )
        )
        clips = result.scalars().all()

        removed = 0
        for clip in clips:
            try:
                if clip.storage_ref:
                    await storage.delete(clip.storage_ref)
                await session.delete(clip)
                removed += 1
            except Exception:
                logger.exception("Falha ao remover clipe expirado %s", clip.id)

        await session.commit()
        logger.info(
            "Limpeza de clipes: %d removidos (retenção=%dd)", removed, settings.clip_retention_days
        )
