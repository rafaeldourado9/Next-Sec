"""Repositório SQLAlchemy para auditoria."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.audit.domain import AuditLog
from vms.audit.models import AuditLogModel


class AuditRepositoryPort(Protocol):
    """Interface do repositório de auditoria."""

    async def create(self, audit_log: AuditLog) -> AuditLog: ...
    async def list_by_tenant(
        self,
        tenant_id: str,
        action: str | None = None,
        user_id: str | None = None,
        resource_type: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]: ...


def _to_domain(model: AuditLogModel) -> AuditLog:
    """Converte modelo ORM para entidade de domínio."""
    return AuditLog(
        id=model.id,
        tenant_id=model.tenant_id,
        user_id=model.user_id,
        user_email=model.user_email,
        user_role=model.user_role,
        action=model.action,
        resource_type=model.resource_type,
        resource_id=model.resource_id,
        resource_name=model.resource_name,
        ip_address=model.ip_address,
        user_agent=model.user_agent,
        request_id=model.request_id,
        payload=model.payload or {},
        result=model.result or "success",
        occurred_at=model.occurred_at or datetime.now(),
    )


def _id_to_str(value: object | None) -> str | None:
    """Normaliza value objects/UUIDs para colunas UUID(as_uuid=False)."""
    if value is None:
        return None
    raw = value.value if hasattr(value, "value") else value
    return str(raw)


class AuditRepository:
    """Repositório SQLAlchemy para AuditLog."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, audit_log: AuditLog) -> AuditLog:
        """Persiste novo log de auditoria.

        Regra: NUNCA UPDATE ou DELETE. Apenas INSERT.
        """
        model = AuditLogModel(
            id=_id_to_str(audit_log.id),
            tenant_id=_id_to_str(audit_log.tenant_id),
            user_id=_id_to_str(audit_log.user_id),
            user_email=audit_log.user_email,
            user_role=audit_log.user_role,
            action=audit_log.action,
            resource_type=audit_log.resource_type,
            resource_id=_id_to_str(audit_log.resource_id),
            resource_name=audit_log.resource_name,
            ip_address=audit_log.ip_address,
            user_agent=audit_log.user_agent,
            request_id=_id_to_str(audit_log.request_id),
            payload=audit_log.payload,
            result=audit_log.result,
            occurred_at=audit_log.occurred_at,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def list_by_tenant(
        self,
        tenant_id: str,
        action: str | None = None,
        user_id: str | None = None,
        resource_type: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        """Lista logs de auditoria com filtros.

        Returns:
            Tuple de (items, total_count)
        """
        base = select(AuditLogModel).where(AuditLogModel.tenant_id == tenant_id)

        if action:
            base = base.where(AuditLogModel.action == action)
        if user_id:
            base = base.where(AuditLogModel.user_id == user_id)
        if resource_type:
            base = base.where(AuditLogModel.resource_type == resource_type)
        if from_date:
            base = base.where(AuditLogModel.occurred_at >= from_date)
        if to_date:
            base = base.where(AuditLogModel.occurred_at <= to_date)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = await self._session.scalar(count_stmt) or 0

        # Query
        stmt = base.order_by(AuditLogModel.occurred_at.desc()).limit(limit).offset(offset)
        result = await self._session.scalars(stmt)
        return [_to_domain(m) for m in result.all()], total
