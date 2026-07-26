"""Tarefas ARQ para dispatch assíncrono de notificações."""
from __future__ import annotations

import logging

from vms.infrastructure.database import get_session_factory
from vms.notifications.repository import NotificationRuleRepository
from vms.notifications.dispatcher import dispatch_webhook
from vms.notifications.repository import NotificationLogRepository

logger = logging.getLogger(__name__)


async def task_dispatch_notification(
    ctx: dict,
    rule_id: str,
    event_type: str,
    event_id: str,
    payload: dict,
) -> None:
    """
    Envia webhook para uma regra de notificação.

    Busca a regra no banco, invoca o dispatcher e persiste o log resultante.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            rule_repo = NotificationRuleRepository(session)
            # Busca a regra sem filtrar por tenant — o rule_id é suficiente aqui
            # pois a tarefa é enfileirada internamente com IDs confiáveis
            from sqlalchemy import select
            from vms.notifications.models import NotificationRuleModel
            stmt = select(NotificationRuleModel).where(
                NotificationRuleModel.id == rule_id
            )
            model = await session.scalar(stmt)
            if not model:
                logger.warning("Regra não encontrada para dispatch: %s", rule_id)
                return

            from vms.notifications.domain import NotificationRule
            rule = NotificationRule(
                id=model.id,
                tenant_id=model.tenant_id,
                name=model.name,
                event_type_pattern=model.event_type_pattern,
                destination_url=model.destination_url,
                webhook_secret=model.webhook_secret,
                is_active=model.is_active,
                created_at=model.created_at,
            )

            log = await dispatch_webhook(
                rule,
                event_type,
                event_id,
                payload,
                client=ctx.get("http_client"),
            )
            log_repo = NotificationLogRepository(session)
            await log_repo.create(log)
            await session.commit()

            logger.info(
                "Webhook despachado: rule=%s event=%s status=%s",
                rule_id, event_id, log.status,
            )
        except Exception as exc:
            await session.rollback()
            logger.exception("Erro ao despachar notificação: rule=%s event=%s", rule_id, event_id)
            # Registra falha na DLQ
            try:
                from vms.infrastructure.messaging import record_failure
                job_id = ctx.get("job_id", f"{rule_id}:{event_id}")
                await record_failure(
                    ctx["redis"],
                    "task_dispatch_notification",
                    str(job_id),
                    str(exc),
                )
            except Exception:
                pass
            raise
