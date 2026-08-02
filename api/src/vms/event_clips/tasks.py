"""Tarefa ARQ de limpeza de clipes antigos (retenção — ver ADR-010 revisado).

Disco da VPS é compartilhado (ADR-005) — clipes acumulados sem limite
esgotariam os 96GB disponíveis. Roda diariamente, remove do storage e do
banco os clipes mais antigos que a retenção **daquele cliente**.

A retenção passou a ser por licença na ADR-018 §4 (`license_keys.
clip_retention_days`, default 30): com a VPS multi-tenant guardando clipe de
15 s de milhares de instalações, um número global obrigaria a dimensionar tudo
pelo cliente mais exigente. `CLIP_RETENTION_DAYS` (env) continua valendo como
fallback para tenant sem licença ativa — webhooks de câmera e setups Nível 3
criam evento sem passar por ativação de edge.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from vms.billing.models import LicenseKeyModel
from vms.event_clips.models import EventClipModel
from vms.infrastructure.config import get_settings
from vms.infrastructure.database import get_session_factory
from vms.infrastructure.storage_provider import build_storage_provider

logger = logging.getLogger(__name__)


async def task_cleanup_old_clips(ctx: dict) -> None:
    """Remove clipes mais antigos que a retenção da licença de cada tenant."""
    settings = get_settings()
    default_retention_days = settings.clip_retention_days
    storage = build_storage_provider()
    now = datetime.now(UTC)

    factory = get_session_factory()
    async with factory() as session:
        retention_by_tenant = {
            tenant_id: days
            for tenant_id, days in (await session.execute(
                select(LicenseKeyModel.tenant_id, LicenseKeyModel.clip_retention_days).where(
                    LicenseKeyModel.tenant_id.is_not(None),
                    LicenseKeyModel.status == "active",
                )
            )).all()
        }

        # Busca pela retenção mais LONGA em uso e filtra por tenant em memória:
        # uma query por tenant seria N round-trips por noite, e a alternativa
        # (CASE por tenant no SQL) não caberia com milhares de clientes.
        longest_retention = max(
            [default_retention_days, *retention_by_tenant.values()], default=default_retention_days
        )
        candidates = (await session.execute(
            select(EventClipModel).where(
                EventClipModel.created_at < now - timedelta(days=longest_retention),
                EventClipModel.status == "uploaded",
            )
        )).scalars().all()

        removed = 0
        freed_bytes = 0
        for clip in candidates:
            retention_days = retention_by_tenant.get(clip.tenant_id, default_retention_days)
            created_at = clip.created_at
            if created_at is not None and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if created_at is not None and created_at >= now - timedelta(days=retention_days):
                continue

            try:
                if clip.storage_ref:
                    await storage.delete(clip.storage_ref)
                freed_bytes += clip.size_bytes or 0
                await session.delete(clip)
                removed += 1
            except Exception:
                logger.exception("Falha ao remover clipe expirado %s", clip.id)

        await session.commit()
        logger.info(
            "Limpeza de clipes: %d removidos, %.1f MB liberados (retenção default=%dd, "
            "%d tenants com retenção própria)",
            removed, freed_bytes / (1024 * 1024), default_retention_days, len(retention_by_tenant),
        )
