"""Ports (interfaces) e implementações SQLAlchemy para notificações."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.notifications.domain import NotificationLog, NotificationRule, NotificationStatus
from vms.notifications.models import NotificationLogModel, NotificationRuleModel


# ─── Ports (interfaces) ───────────────────────────────────────────────────────

class NotificationRuleRepositoryPort(Protocol):
    """Interface do repositório de regras de notificação."""

    async def list_by_tenant(
        self, tenant_id: str, active_only: bool = True
    ) -> list[NotificationRule]: ...

    async def get_by_id(
        self, rule_id: str, tenant_id: str
    ) -> NotificationRule | None: ...

    async def create(self, rule: NotificationRule) -> NotificationRule: ...

    async def update_active(
        self, rule_id: str, tenant_id: str, is_active: bool
    ) -> NotificationRule | None: ...

    async def delete(self, rule_id: str, tenant_id: str) -> bool: ...


class NotificationLogRepositoryPort(Protocol):
    """Interface do repositório de logs de notificação."""

    async def create(self, log: NotificationLog) -> NotificationLog: ...

    async def list_by_tenant(
        self,
        tenant_id: str,
        rule_id: str | None = None,
        status: NotificationStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NotificationLog]: ...


# ─── Conversores ORM ↔ Domain ─────────────────────────────────────────────────

def _rule_to_domain(m: NotificationRuleModel) -> NotificationRule:
    """Converte modelo ORM para entidade de domínio."""
    return NotificationRule(
        id=m.id,
        tenant_id=m.tenant_id,
        name=m.name,
        event_type_pattern=m.event_type_pattern,
        destination_url=m.destination_url,
        webhook_secret=m.webhook_secret,
        is_active=m.is_active,
        created_at=m.created_at,
    )


def _log_to_domain(m: NotificationLogModel) -> NotificationLog:
    """Converte modelo ORM para entidade de domínio."""
    return NotificationLog(
        id=m.id,
        tenant_id=m.tenant_id,
        rule_id=m.rule_id,
        vms_event_id=m.vms_event_id,
        status=NotificationStatus(m.status),
        response_code=m.response_code,
        response_body=m.response_body,
        attempt=m.attempt,
        dispatched_at=m.dispatched_at,
    )


# ─── Implementações SQLAlchemy ────────────────────────────────────────────────

class NotificationRuleRepository:
    """Repositório SQLAlchemy para NotificationRule."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_tenant(
        self, tenant_id: str, active_only: bool = True
    ) -> list[NotificationRule]:
        """Lista regras do tenant, opcionalmente filtrando apenas ativas."""
        stmt = select(NotificationRuleModel).where(
            NotificationRuleModel.tenant_id == tenant_id
        )
        if active_only:
            stmt = stmt.where(NotificationRuleModel.is_active.is_(True))
        result = await self._session.scalars(stmt)
        return [_rule_to_domain(m) for m in result.all()]

    async def get_by_id(
        self, rule_id: str, tenant_id: str
    ) -> NotificationRule | None:
        """Busca regra por ID dentro do tenant."""
        stmt = select(NotificationRuleModel).where(
            NotificationRuleModel.id == rule_id,
            NotificationRuleModel.tenant_id == tenant_id,
        )
        result = await self._session.scalar(stmt)
        return _rule_to_domain(result) if result else None

    async def create(self, rule: NotificationRule) -> NotificationRule:
        """Persiste nova regra de notificação."""
        model = NotificationRuleModel(
            id=rule.id or str(uuid.uuid4()),
            tenant_id=rule.tenant_id,
            name=rule.name,
            event_type_pattern=rule.event_type_pattern,
            destination_url=rule.destination_url,
            webhook_secret=rule.webhook_secret,
            is_active=rule.is_active,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _rule_to_domain(model)

    async def update_active(
        self, rule_id: str, tenant_id: str, is_active: bool
    ) -> NotificationRule | None:
        """Ativa ou desativa uma regra. Retorna None se não encontrada."""
        stmt = select(NotificationRuleModel).where(
            NotificationRuleModel.id == rule_id,
            NotificationRuleModel.tenant_id == tenant_id,
        )
        model = await self._session.scalar(stmt)
        if not model:
            return None
        model.is_active = is_active
        await self._session.flush()
        await self._session.refresh(model)
        return _rule_to_domain(model)

    async def delete(self, rule_id: str, tenant_id: str) -> bool:
        """Remove regra permanentemente. Retorna False se não encontrada."""
        stmt = select(NotificationRuleModel).where(
            NotificationRuleModel.id == rule_id,
            NotificationRuleModel.tenant_id == tenant_id,
        )
        model = await self._session.scalar(stmt)
        if not model:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True


class NotificationLogRepository:
    """Repositório SQLAlchemy para NotificationLog."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, log: NotificationLog) -> NotificationLog:
        """Persiste log de dispatch."""
        model = NotificationLogModel(
            id=log.id or str(uuid.uuid4()),
            tenant_id=log.tenant_id,
            rule_id=log.rule_id,
            vms_event_id=log.vms_event_id,
            status=log.status.value,
            response_code=log.response_code,
            response_body=log.response_body,
            attempt=log.attempt,
            dispatched_at=log.dispatched_at or datetime.now(UTC),
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        saved = _log_to_domain(model)
        await self._session.commit()
        return saved

    async def list_by_tenant(
        self,
        tenant_id: str,
        rule_id: str | None = None,
        status: NotificationStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NotificationLog]:
        """Lista logs do tenant com filtros opcionais."""
        stmt = (
            select(NotificationLogModel)
            .where(NotificationLogModel.tenant_id == tenant_id)
            .order_by(NotificationLogModel.dispatched_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if rule_id:
            stmt = stmt.where(NotificationLogModel.rule_id == rule_id)
        if status:
            stmt = stmt.where(NotificationLogModel.status == status.value)
        result = await self._session.scalars(stmt)
        return [_log_to_domain(m) for m in result.all()]
