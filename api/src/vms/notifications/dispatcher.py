"""Dispatcher assíncrono de webhooks com HMAC-SHA256."""
from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager

import httpx
from datetime import UTC, datetime

from vms.infrastructure.security import sign_webhook_payload
from vms.notifications.domain import NotificationLog, NotificationRule, NotificationStatus

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _get_client(client: httpx.AsyncClient | None):
    """Usa o client fornecido (pooled) ou cria um temporário se None."""
    if client is not None:
        yield client
    else:
        async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "VMS-Webhook/1.0"}) as c:
            yield c


async def dispatch_webhook(
    rule: NotificationRule,
    event_type: str,
    event_id: str,
    payload: dict,
    *,
    client: httpx.AsyncClient | None = None,
) -> NotificationLog:
    """Envia webhook para destination_url da regra com assinatura HMAC.

    Passe ``client`` para reutilizar uma conexão keep-alive entre chamadas
    (obtido de ``ctx["http_client"]`` no worker ARQ).
    Sem ``client``, cria e fecha um client temporário (modo compatível).

    Headers enviados:
    - X-VMS-Signature: sha256={hmac_hex}
    - X-VMS-Event: event_type
    - Content-Type: application/json
    """
    body = json.dumps(
        {
            "event_type": event_type,
            "event_id": event_id,
            "payload": payload,
            "timestamp": datetime.now(UTC).isoformat(),
        },
        default=str,
    ).encode()

    signature = sign_webhook_payload(body, rule.webhook_secret)

    try:
        async with _get_client(client) as http:
            response = await http.post(
                rule.destination_url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-VMS-Signature": f"sha256={signature}",
                    "X-VMS-Event": event_type,
                },
            )

        status = (
            NotificationStatus.SUCCESS
            if response.is_success
            else NotificationStatus.FAILED
        )
        return NotificationLog(
            id=str(uuid.uuid4()),
            tenant_id=rule.tenant_id,
            rule_id=rule.id,
            vms_event_id=event_id,
            status=status,
            response_code=response.status_code,
            response_body=response.text[:500],
        )
    except Exception as exc:
        logger.error(
            "Erro ao disparar webhook para %s: %s", rule.destination_url, exc
        )
        return NotificationLog(
            id=str(uuid.uuid4()),
            tenant_id=rule.tenant_id,
            rule_id=rule.id,
            vms_event_id=event_id,
            status=NotificationStatus.FAILED,
            response_body=str(exc)[:500],
        )
