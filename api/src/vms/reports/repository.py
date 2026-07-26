"""Repositório SQLAlchemy para relatórios."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.reports.domain import Report, ReportStatus, ReportType
from vms.reports.models import ReportModel


class ReportRepositoryPort(Protocol):
    """Interface do repositório de relatórios."""

    async def create(self, report: Report) -> Report: ...
    async def get_by_id(self, report_id: str, tenant_id: str) -> Report | None: ...
    async def list_by_tenant(
        self,
        tenant_id: str,
        report_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Report], int]: ...
    async def update(self, report: Report) -> Report: ...


def _to_domain(model: ReportModel) -> Report:
    """Converte modelo ORM para entidade de domínio."""
    return Report(
        id=model.id,
        tenant_id=model.tenant_id,
        report_type=ReportType(model.report_type) if model.report_type else None,
        parameters=model.parameters or {},
        status=ReportStatus(model.status),
        file_path=model.file_path,
        sha256_hash=model.sha256_hash,
        scheduled_for=model.scheduled_for,
        generated_at=model.generated_at,
        created_by=model.created_by,
        created_at=model.created_at,
    )


class ReportRepository:
    """Repositório SQLAlchemy para Report."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, report: Report) -> Report:
        """Cria novo relatório."""
        model = ReportModel(
            id=report.id.value if hasattr(report.id, 'value') else report.id,
            tenant_id=report.tenant_id.value if hasattr(report.tenant_id, 'value') else report.tenant_id,
            report_type=report.report_type,
            parameters=report.parameters,
            status=report.status,
            file_path=report.file_path,
            sha256_hash=report.sha256_hash,
            scheduled_for=report.scheduled_for,
            generated_at=report.generated_at,
            created_by=report.created_by,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, report_id: str, tenant_id: str) -> Report | None:
        """Busca relatório por ID e tenant."""
        stmt = select(ReportModel).where(
            ReportModel.id == report_id,
            ReportModel.tenant_id == tenant_id,
        )
        model = await self._session.scalar(stmt)
        return _to_domain(model) if model else None

    async def list_by_tenant(
        self,
        tenant_id: str,
        report_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Report], int]:
        """Lista relatórios do tenant."""
        base = select(ReportModel).where(ReportModel.tenant_id == tenant_id)
        if report_type:
            base = base.where(ReportModel.report_type == report_type)
        if status:
            base = base.where(ReportModel.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = await self._session.scalar(count_stmt) or 0

        stmt = base.order_by(ReportModel.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.scalars(stmt)
        return [_to_domain(m) for m in result.all()], total

    async def update(self, report: Report) -> Report:
        """Atualiza relatório existente."""
        from sqlalchemy import update as sa_update

        stmt = (
            sa_update(ReportModel)
            .where(
                ReportModel.id == report.id.value if hasattr(report.id, 'value') else report.id,
                ReportModel.tenant_id == report.tenant_id.value if hasattr(report.tenant_id, 'value') else report.tenant_id,
            )
            .values(
                status=report.status,
                file_path=report.file_path,
                sha256_hash=report.sha256_hash,
                generated_at=report.generated_at,
            )
        )
        await self._session.execute(stmt)
        return report
