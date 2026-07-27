"""Application service de notificações — casos de uso de regras e dispatch."""
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from vms.shared.exceptions import NotFoundError
from vms.notifications.dispatcher import dispatch_channel, dispatch_webhook
from vms.notifications.domain import NotificationLog, NotificationRule
from vms.notifications.repository import (
    NotificationLogRepository,
    NotificationLogRepositoryPort,
    NotificationRuleRepository,
    NotificationRuleRepositoryPort,
)

logger = logging.getLogger(__name__)


class NotificationService:
    """Casos de uso de gerenciamento de regras e dispatch de notificações."""

    def __init__(
        self,
        rule_repo: NotificationRuleRepositoryPort,
        log_repo: NotificationLogRepositoryPort,
        contact_repo: object | None = None,
    ) -> None:
        self._rules = rule_repo
        self._logs = log_repo
        self._contacts = contact_repo

    async def create_rule(
        self,
        tenant_id: str,
        name: str,
        pattern: str,
        destination_type: str = "webhook",
        dest_url: str | None = None,
        secret: str | None = None,
        contact_id: str | None = None,
        channel: str = "whatsapp",
    ) -> NotificationRule:
        """Cria nova regra de notificação para o tenant.

        `destination_type='webhook'` exige `dest_url`+`secret`.
        `destination_type='contact'` exige `contact_id` — ver ADR-009.
        """
        if destination_type == "webhook" and not dest_url:
            raise ValueError("destination_url é obrigatório para destination_type='webhook'")
        if destination_type == "contact" and not contact_id:
            raise ValueError("contact_id é obrigatório para destination_type='contact'")

        rule = NotificationRule(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=name,
            event_type_pattern=pattern,
            destination_type=destination_type,
            destination_url=dest_url,
            webhook_secret=secret,
            contact_id=contact_id,
            channel=channel,
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
        *,
        message: str | None = None,
        media_bytes: bytes | None = None,
        media_type: str = "image",
        mime_type: str = "image/jpeg",
    ) -> list[NotificationLog]:
        """
        Avalia regras ativas do tenant e dispara a notificação (webhook ou
        canal/contato, conforme `destination_type` de cada regra) para as
        que casam com `event_type`.

        `message`/`media_bytes` só são usados por regras `destination_type=contact`
        — regras `webhook` continuam usando o payload bruto (comportamento herdado).
        Persiste um NotificationLog para cada tentativa de dispatch.
        """
        rules = await self._rules.list_by_tenant(tenant_id, active_only=True)
        matching = [r for r in rules if r.matches(event_type)]

        # Dispara todas as regras em paralelo — não sequencial. Uma regra
        # lenta ou quebrada (ex.: número de WhatsApp que sempre falha e faz
        # 3 tentativas com backoff, ~3.5s) não pode atrasar a notificação das
        # outras regras que funcionam normalmente (achado em teste local:
        # regra ruim no meio da lista segurava a notificação da regra boa
        # até terminar de tentar e desistir).
        async def _dispatch_one(rule: NotificationRule) -> NotificationLog | None:
            if rule.destination_type == "contact":
                if not self._contacts or not rule.contact_id:
                    logger.warning(
                        "Regra %s é destination_type=contact mas sem contact_id/repo — pulando",
                        rule.id,
                    )
                    return None
                contact = await self._contacts.get_by_id(rule.contact_id, tenant_id)
                if not contact or not contact.is_active:
                    logger.info(
                        "Contato %s inativo/removido — notificação da regra %s não enviada",
                        rule.contact_id, rule.id,
                    )
                    return None
                return await dispatch_channel(
                    rule, event_type, event_id,
                    phone_number=contact.phone_number,
                    message=message or f"Alerta: {event_type}",
                    media_bytes=media_bytes,
                    media_type=media_type,
                    mime_type=mime_type,
                )
            return await dispatch_webhook(rule, event_type, event_id, payload)

        results = await asyncio.gather(*(_dispatch_one(rule) for rule in matching))

        logs: list[NotificationLog] = []
        for log in results:
            if log is None:
                continue
            saved = await self._logs.create(log)
            logs.append(saved)

        return logs


def build_notification_service(session: AsyncSession) -> NotificationService:
    """Factory que constrói NotificationService com implementações concretas."""
    from vms.contacts.repository import ContactRepository

    return NotificationService(
        rule_repo=NotificationRuleRepository(session),
        log_repo=NotificationLogRepository(session),
        contact_repo=ContactRepository(session),
    )
