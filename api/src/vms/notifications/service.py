"""Application service de notificações — casos de uso de regras e dispatch."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from vms.shared.exceptions import NotFoundError
from vms.notifications.dispatcher import dispatch_webhook
from vms.notifications.domain import NotificationLog, NotificationRule
from vms.notifications.repository import (
    NotificationLogRepository,
    NotificationLogRepositoryPort,
    NotificationRuleRepository,
    NotificationRuleRepositoryPort,
)


class NotificationService:
    """Casos de uso de gerenciamento de regras e dispatch de webhooks."""

    def __init__(
        self,
        rule_repo: NotificationRuleRepositoryPort,
        log_repo: NotificationLogRepositoryPort,
    ) -> None:
        self._rules = rule_repo
        self._logs = log_repo

    async def create_rule(
        self,
        tenant_id: str,
        name: str,
        pattern: str,
        dest_url: str,
        secret: str,
    ) -> NotificationRule:
        """Cria nova regra de notificação para o tenant."""
        rule = NotificationRule(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=name,
            event_type_pattern=pattern,
            destination_url=dest_url,
            webhook_secret=secret,
        )
        return await self._rules.create(rule)

    async def list_rules(self, tenant_id: str) -> list[NotificationRule]:
        """Lista todas as regras ativas do tenant."""
        return await self._rules.list_by_tenant(tenant_id, active_only=False)

    async def get_rule(self, rule_id: str, tenant_id: str) -> NotificationRule:
        """Retorna regra por ID. Lança NotFoundError se não encontrada."""
        rule = await self._rules.get_by_id(rule_id, tenant_id)
        if not rule:
            raise NotFoundError("NotificationRule", rule_id)
        return rule

    async def delete_rule(self, rule_id: str, tenant_id: str) -> None:
        """Remove regra permanentemente. Lança NotFoundError se não encontrada."""
        deleted = await self._rules.delete(rule_id, tenant_id)
        if not deleted:
            raise NotFoundError("NotificationRule", rule_id)

    async def evaluate_and_dispatch(
        self,
        tenant_id: str,
        event_type: str,
        event_id: str,
        payload: dict,
    ) -> list[NotificationLog]:
        """
        Avalia regras ativas do tenant e dispara webhooks para as que casam.

        Persiste um NotificationLog para cada tentativa de dispatch.
        """
        rules = await self._rules.list_by_tenant(tenant_id, active_only=True)
        matching = [r for r in rules if r.matches(event_type)]

        logs: list[NotificationLog] = []
        for rule in matching:
            log = await dispatch_webhook(rule, event_type, event_id, payload)
            saved = await self._logs.create(log)
            logs.append(saved)

        return logs


def build_notification_service(session: AsyncSession) -> NotificationService:
    """Factory que constrói NotificationService com implementações concretas."""
    return NotificationService(
        rule_repo=NotificationRuleRepository(session),
        log_repo=NotificationLogRepository(session),
    )
