"""Tarefas ARQ para geração de relatórios."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from vms.reports.domain import ReportType
from vms.reports.repository import ReportRepository
from vms.reports.service import ReportService
from vms.infrastructure.database import get_session_factory

logger = logging.getLogger(__name__)

_PDF_SEM_KEY = "arq:sem:pdf_generation"
_PDF_SEM_LIMIT = 2   # máx PDFs gerados em paralelo — cada um pode usar 200–500 MB RAM
_PDF_SEM_TTL = 660   # TTL Redis em segundos — auto-libera se worker crashar


@asynccontextmanager
async def _pdf_semaphore(redis, timeout: int = 60) -> AsyncIterator[None]:
    """Semáforo distribuído via Redis INCR/DECR.

    Bloqueia até conseguir slot ou lança TimeoutError após ``timeout`` segundos.
    O TTL garante liberação automática mesmo em crash do worker.
    """
    loop = asyncio.get_event_loop()
    start = loop.time()
    while True:
        count = await redis.incr(_PDF_SEM_KEY)
        await redis.expire(_PDF_SEM_KEY, _PDF_SEM_TTL)
        if count <= _PDF_SEM_LIMIT:
            break
        await redis.decr(_PDF_SEM_KEY)
        if loop.time() - start > timeout:
            raise TimeoutError(
                f"PDF semaphore esgotado após {timeout}s — "
                f"{_PDF_SEM_LIMIT} relatórios já em geração"
            )
        await asyncio.sleep(3)
    try:
        yield
    finally:
        await redis.decr(_PDF_SEM_KEY)


async def task_generate_report(ctx: dict, report_id: str) -> None:
    """Gera relatório PDF solicitado via ARQ.

    Limitado a _PDF_SEM_LIMIT execuções paralelas para evitar spike de RAM.
    """
    redis = ctx.get("redis")
    factory = get_session_factory()

    sem = _pdf_semaphore(redis) if redis else _noop_ctx()
    async with sem:
        async with factory() as session:
            try:
                repo = ReportRepository(session)
                svc = ReportService(repo)

                report = await repo.get_by_id(report_id, tenant_id="*")
                if not report:
                    logger.warning("Relatório %s não encontrado para task", report_id)
                    return

                data = await _collect_data_for_task(report, session)
                branding = await _fetch_branding_for_task(report.tenant_id, session)
                await svc.generate_report_pdf(report, data, branding=branding)

                await session.commit()
                logger.info("Relatório %s gerado com sucesso", report_id)
            except Exception:
                await session.rollback()
                logger.exception("Falha ao gerar relatório %s", report_id)


@asynccontextmanager
async def _noop_ctx() -> AsyncIterator[None]:
    """Fallback quando Redis não está disponível no contexto."""
    yield


async def _collect_data_for_task(report, session) -> dict:
    """Coleta dados para geração assíncrona de relatório."""
    from sqlalchemy import select
    from datetime import datetime, timedelta

    tenant_id = report.tenant_id
    report_type = report.report_type
    params = report.parameters or {}

    if report_type == ReportType.CAMERAS_STATUS:
        from vms.cameras.models import CameraModel
        stmt = select(CameraModel).where(CameraModel.tenant_id == tenant_id)
        result = await session.execute(stmt)
        cameras = result.scalars().all()
        online = sum(1 for c in cameras if c.is_online)
        return {"cameras": cameras, "online_count": online, "offline_count": len(cameras) - online}

    if report_type == ReportType.EVENTS_SUMMARY:
        from vms.events.models import VmsEventModel
        period_days = params.get("period_days", 7)
        cutoff = datetime.utcnow() - timedelta(days=period_days)
        stmt = (
            select(VmsEventModel)
            .where(VmsEventModel.tenant_id == tenant_id, VmsEventModel.occurred_at >= cutoff)
            .order_by(VmsEventModel.occurred_at.desc())
            .limit(1000)
        )
        result = await session.execute(stmt)
        events = result.scalars().all()
        type_counts = {}
        for e in events:
            t = e.event_type or "unknown"
            type_counts[t] = type_counts.get(t, 0) + 1
        return {"events": events, "summary": type_counts, "total_events": len(events)}

    # RECORDINGS_COVERAGE removido — gravação contínua fora do escopo do
    # Next Sec (ver .genesis/architecture/reuse-plan.md)

    if report_type == ReportType.AUDIT_TRAIL:
        from vms.audit.models import AuditLogModel
        period_days = params.get("period_days", 7)
        cutoff = datetime.utcnow() - timedelta(days=period_days)
        stmt = (
            select(AuditLogModel)
            .where(AuditLogModel.tenant_id == tenant_id, AuditLogModel.occurred_at >= cutoff)
            .order_by(AuditLogModel.occurred_at.desc())
            .limit(500)
        )
        result = await session.execute(stmt)
        logs = result.scalars().all()
        action_counts = {}
        for log in logs:
            a = log.action or "unknown"
            action_counts[a] = action_counts.get(a, 0) + 1
        return {"audit_logs": logs, "summary": action_counts, "total_logs": len(logs)}

    if report_type == ReportType.ANALYTICS_EVENTS:
        from vms.analytics.models import AnalyticsEventModel
        period_days = params.get("period_days", 7)
        cutoff = datetime.utcnow() - timedelta(days=period_days)
        stmt = (
            select(AnalyticsEventModel)
            .where(AnalyticsEventModel.tenant_id == tenant_id, AnalyticsEventModel.occurred_at >= cutoff)
            .order_by(AnalyticsEventModel.occurred_at.desc())
            .limit(1000)
        )
        result = await session.execute(stmt)
        events = result.scalars().all()
        plugin_counts = {}
        for e in events:
            p = e.plugin_name or "unknown"
            plugin_counts[p] = plugin_counts.get(p, 0) + 1
        return {"analytics_events": events, "summary": plugin_counts, "total_events": len(events)}

    return {"events": [], "summary": {}, "total_events": 0}


async def task_auto_monthly_report(ctx: dict) -> None:
    """Cron mensal: gera relatórios CAMERAS_STATUS + EVENTS_SUMMARY para todos os tenants ativos."""
    from vms.infrastructure.database import get_session_factory
    from vms.iam.models import TenantModel
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as session:
        try:
            tenants = (await session.execute(
                select(TenantModel).where(
                    TenantModel.is_active.is_(True),
                    TenantModel.onboarding_complete.is_(True),
                )
            )).scalars().all()

            for tenant in tenants:
                tenant_id = str(tenant.id)
                for rtype in (ReportType.CAMERAS_STATUS, ReportType.EVENTS_SUMMARY):
                    try:
                        repo = ReportRepository(session)
                        svc = ReportService(repo)
                        report = await svc.create_report(
                            tenant_id=tenant_id,
                            report_type=rtype,
                            parameters={"period_days": 30, "auto": True},
                        )
                        data = await _collect_data_for_task(report, session)
                        branding = await _fetch_branding_for_task(tenant_id, session)
                        await svc.generate_report_pdf(report, data, branding=branding)
                        await session.commit()
                        logger.info(
                            "Relatório mensal %s gerado para tenant %s", rtype, tenant_id
                        )
                    except Exception:
                        await session.rollback()
                        logger.exception(
                            "Falha ao gerar relatório mensal %s para tenant %s", rtype, tenant_id
                        )
        except Exception:
            logger.exception("Falha na task cron de relatórios mensais")


async def _fetch_branding_for_task(tenant_id: str, session) -> dict:
    """Busca dados de branding do tenant (contexto de task ARQ)."""
    from sqlalchemy import select
    from vms.iam.models import TenantModel
    tenant = await session.scalar(select(TenantModel).where(TenantModel.id == tenant_id))
    if not tenant:
        return {}
    return {
        "company_name": getattr(tenant, 'company_name', None),
        "cnpj": getattr(tenant, 'cnpj', None),
        "company_address": getattr(tenant, 'company_address', None),
        "logo_url": getattr(tenant, 'logo_url', None),
    }
