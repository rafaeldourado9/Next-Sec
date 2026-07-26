"""Rotas HTTP para relatórios."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from vms.shared.api.dependencies import CurrentUser, DbSession
from vms.reports.domain import ReportType
from vms.reports.repository import ReportRepository
from vms.reports.schemas import CreateReportRequest, ReportListResponse, ReportResponse
from vms.reports.service import ReportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


def _report_svc(db: DbSession) -> ReportService:
    return ReportService(ReportRepository(db))


@router.post(
    "",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Solicitar relatório",
)
async def request_report(
    body: CreateReportRequest,
    claims: CurrentUser,
    db: DbSession,
    request: Request,
    bg: BackgroundTasks,
) -> ReportResponse:
    """Solicita geração de relatório. Processamento assíncrono via ARQ."""
    svc = _report_svc(db)

    report = await svc.create_report(
        tenant_id=claims.tenant_id,
        report_type=body.report_type,
        parameters=body.parameters,
        user_id=claims.user_id,
    )

    # Enfileirar task ARQ
    report_id_str = str(report.id.value) if hasattr(report.id, 'value') else str(report.id)
    try:
        arq_pool = getattr(request.app.state, 'arq_redis', None)
        if arq_pool and hasattr(arq_pool, 'enqueue_job'):
            await arq_pool.enqueue_job(
                'task_generate_report',
                report_id_str,
                _queue_name='arq:low',
            )
            logger.info("Task ARQ enfileirada para relatório %s", report_id_str)
        else:
            # Fallback: gerar em background task FastAPI
            bg.add_task(_bg_generate, report_id_str)
            logger.info("Relatório %s agendado via BackgroundTasks (ARQ indisponível)", report_id_str)
    except Exception:
        bg.add_task(_bg_generate, report_id_str)
        logger.warning("ARQ falhou, usando BackgroundTasks para relatório %s", report_id_str)

    return ReportResponse.model_validate(report)


async def _bg_generate(report_id: str) -> None:
    """Fallback: gera relatório em background quando ARQ não disponível."""
    from vms.reports.tasks import task_generate_report
    await task_generate_report({}, report_id)


@router.post(
    "/{report_id}/generate-now",
    response_model=ReportResponse,
    summary="Gerar relatório imediatamente (síncrono, para testes)",
)
async def generate_report_now(
    report_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> ReportResponse:
    """Força geração síncrona do relatório. Útil para testes e relatórios pequenos."""
    svc = _report_svc(db)
    report = await svc.get_report(report_id, claims.tenant_id)
    if not report:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")

    data = await _collect_data(report.report_type, report.parameters, claims.tenant_id, db)
    branding = await _fetch_branding(claims.tenant_id, db)
    await svc.generate_report_pdf(report, data, branding=branding)

    return ReportResponse.model_validate(report)


@router.get(
    "/{report_id}",
    response_model=ReportResponse,
    summary="Status do relatório",
)
async def get_report(
    report_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> ReportResponse:
    """Retorna status do relatório."""
    svc = _report_svc(db)
    report = await svc.get_report(report_id, claims.tenant_id)
    if not report:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")
    return ReportResponse.model_validate(report)


@router.get(
    "/{report_id}/download",
    summary="Download do relatório",
)
async def download_report(
    report_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> FileResponse:
    """Baixa o PDF do relatório."""
    svc = _report_svc(db)
    report = await svc.get_report(report_id, claims.tenant_id)
    if not report:
        raise HTTPException(status_code=404, detail="Relatório não disponível")

    if not report.is_ready:
        raise HTTPException(status_code=400, detail=f"Relatório ainda não está pronto (Status: {report.status})")

    if not report.file_path or not os.path.isfile(report.file_path):
        raise HTTPException(status_code=404, detail="Arquivo de relatório não encontrado")

    return FileResponse(
        path=report.file_path,
        filename=f"relatorio_{report.report_type}_{report.id}.pdf",
        media_type="application/pdf",
    )


@router.get(
    "",
    response_model=ReportListResponse,
    summary="Listar relatórios",
)
async def list_reports(
    claims: CurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ReportListResponse:
    """Lista relatórios do tenant."""
    svc = _report_svc(db)
    items, total = await svc.list_reports(claims.tenant_id, page_size=page_size, page=page)
    return ReportListResponse.build(items, total, page, page_size)


async def _collect_data(report_type: ReportType, params: dict, tenant_id: str, db: DbSession) -> dict:
    """Coleta dados do banco para popular o template."""
    from sqlalchemy import func as sa_func, select

    if report_type == ReportType.CAMERAS_STATUS:
        from vms.cameras.models import CameraModel
        stmt = select(CameraModel).where(CameraModel.tenant_id == tenant_id)
        result = await db.execute(stmt)
        cameras = result.scalars().all()
        online = sum(1 for c in cameras if c.is_online)
        return {
            "cameras": cameras,
            "online_count": online,
            "offline_count": len(cameras) - online,
        }

    if report_type == ReportType.EVENTS_SUMMARY:
        from vms.events.models import VmsEventModel
        from datetime import datetime, timedelta

        period_days = params.get("period_days", 7)
        cutoff = datetime.utcnow() - timedelta(days=period_days)
        stmt = (
            select(VmsEventModel)
            .where(VmsEventModel.tenant_id == tenant_id, VmsEventModel.occurred_at >= cutoff)
            .order_by(VmsEventModel.occurred_at.desc())
            .limit(1000)
        )
        result = await db.execute(stmt)
        events = result.scalars().all()

        # Contagem por tipo
        type_counts: dict[str, int] = {}
        for e in events:
            t = e.event_type or "unknown"
            type_counts[t] = type_counts.get(t, 0) + 1

        return {
            "events": events,
            "summary": type_counts,
            "total_events": len(events),
            "period_days": period_days,
        }

    # RECORDINGS_COVERAGE removido — gravação contínua fora do escopo do
    # Next Sec (ver .genesis/architecture/reuse-plan.md)

    if report_type == ReportType.AUDIT_TRAIL:
        from vms.audit.models import AuditLogModel
        from datetime import datetime, timedelta

        period_days = params.get("period_days", 7)
        cutoff = datetime.utcnow() - timedelta(days=period_days)
        stmt = (
            select(AuditLogModel)
            .where(AuditLogModel.tenant_id == tenant_id, AuditLogModel.occurred_at >= cutoff)
            .order_by(AuditLogModel.occurred_at.desc())
            .limit(500)
        )
        result = await db.execute(stmt)
        logs = result.scalars().all()

        action_counts: dict[str, int] = {}
        for log in logs:
            a = log.action or "unknown"
            action_counts[a] = action_counts.get(a, 0) + 1

        return {
            "audit_logs": logs,
            "summary": action_counts,
            "total_logs": len(logs),
            "period_days": period_days,
        }

    if report_type == ReportType.ANALYTICS_EVENTS:
        from vms.analytics.models import AnalyticsEventModel
        from datetime import datetime, timedelta

        period_days = params.get("period_days", 7)
        cutoff = datetime.utcnow() - timedelta(days=period_days)
        stmt = (
            select(AnalyticsEventModel)
            .where(AnalyticsEventModel.tenant_id == tenant_id, AnalyticsEventModel.occurred_at >= cutoff)
            .order_by(AnalyticsEventModel.occurred_at.desc())
            .limit(1000)
        )
        result = await db.execute(stmt)
        events = result.scalars().all()

        plugin_counts: dict[str, int] = {}
        for e in events:
            p = e.plugin_name or "unknown"
            plugin_counts[p] = plugin_counts.get(p, 0) + 1

        return {
            "analytics_events": events,
            "summary": plugin_counts,
            "total_events": len(events),
            "period_days": period_days,
        }

    # Fallback genérico
    return {"events": [], "summary": {}, "total_events": 0}


async def _fetch_branding(tenant_id: str, db: DbSession) -> dict:
    """Busca dados de branding do tenant para incluir nos PDFs."""
    from sqlalchemy import select
    from vms.iam.models import TenantModel
    tenant = await db.scalar(select(TenantModel).where(TenantModel.id == tenant_id))
    if not tenant:
        return {}
    return {
        "company_name": tenant.company_name,
        "cnpj": tenant.cnpj,
        "company_address": tenant.company_address,
        "logo_url": tenant.logo_url,
    }
