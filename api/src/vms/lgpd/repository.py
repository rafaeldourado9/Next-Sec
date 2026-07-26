"""Repositório SQLAlchemy para Compliance & LGPD."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.lgpd.domain import ConsentRecord, DataType, RetentionPolicy
from vms.lgpd.models import ConsentRecordModel, RetentionPolicyModel


class LgpdRepositoryPort(Protocol):
    """Interface do repositório LGPD."""

    async def get_retention_policy(self, tenant_id: str, data_type: DataType) -> RetentionPolicy | None: ...
    async def get_all_policies(self, tenant_id: str) -> list[RetentionPolicy]: ...
    async def record_consent(self, record: ConsentRecord) -> ConsentRecord: ...
    async def get_latest_consent(self, tenant_id: str, user_id: str, data_type: DataType) -> ConsentRecord | None: ...


def _policy_to_domain(m: RetentionPolicyModel) -> RetentionPolicy:
    return RetentionPolicy(
        id=m.id,
        tenant_id=m.tenant_id,
        data_type=DataType(m.data_type),
        retention_days=m.retention_days,
        anonymize_instead_of_delete=m.anonymize_instead_of_delete if m.anonymize_instead_of_delete is not None else True,
        auto_enabled=m.auto_enabled if m.auto_enabled is not None else True,
        created_at=m.created_at or datetime.utcnow(),
        updated_at=m.updated_at or datetime.utcnow(),
    )


def _consent_to_domain(m: ConsentRecordModel) -> ConsentRecord:
    return ConsentRecord(
        id=m.id,
        tenant_id=m.tenant_id,
        user_id=m.user_id,
        data_type=DataType(m.data_type),
        action=m.action,
        consent_text_hash=m.consent_text_hash,
        ip_address=m.ip_address,
        user_agent=m.user_agent,
        created_at=m.created_at or datetime.utcnow(),
    )


class LgpdRepository:
    """Repositório SQLAlchemy para LGPD."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_retention_policy(self, tenant_id: str, data_type: DataType) -> RetentionPolicy | None:
        stmt = select(RetentionPolicyModel).where(
            RetentionPolicyModel.tenant_id == tenant_id,
            RetentionPolicyModel.data_type == data_type,
        )
        model = await self._session.scalar(stmt)
        return _policy_to_domain(model) if model else None

    async def get_all_policies(self, tenant_id: str) -> list[RetentionPolicy]:
        stmt = select(RetentionPolicyModel).where(
            RetentionPolicyModel.tenant_id == tenant_id,
        )
        result = await self._session.scalars(stmt)
        return [_policy_to_domain(m) for m in result.all()]

    async def record_consent(self, record: ConsentRecord) -> ConsentRecord:
        model = ConsentRecordModel(
            id=record.id if hasattr(record.id, 'value') else record.id,
            tenant_id=record.tenant_id.value if hasattr(record.tenant_id, 'value') else record.tenant_id,
            user_id=record.user_id.value if hasattr(record.user_id, 'value') else record.user_id,
            data_type=record.data_type,
            action=record.action,
            consent_text_hash=record.consent_text_hash,
            ip_address=record.ip_address,
            user_agent=record.user_agent,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _consent_to_domain(model)

    async def get_latest_consent(self, tenant_id: str, user_id: str, data_type: DataType) -> ConsentRecord | None:
        stmt = (
            select(ConsentRecordModel)
            .where(
                ConsentRecordModel.tenant_id == tenant_id,
                ConsentRecordModel.user_id == user_id,
                ConsentRecordModel.data_type == data_type,
            )
            .order_by(ConsentRecordModel.created_at.desc())
            .limit(1)
        )
        model = await self._session.scalar(stmt)
        return _consent_to_domain(model) if model else None
