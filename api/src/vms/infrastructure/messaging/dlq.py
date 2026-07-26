"""Dead Letter Queue para tarefas ARQ que falham repetidamente."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_DLQ_PREFIX = "arq:dlq:"
_FAIL_PREFIX = "arq:fail_count:"
_MAX_RETRIES = 3
_DLQ_TTL = 7 * 24 * 3600  # 7 dias


async def record_failure(
    redis: aioredis.Redis,
    task_name: str,
    job_id: str,
    error: str,
) -> bool:
    """
    Registra falha de task. Retorna True se o limite foi atingido (→ DLQ).

    Incrementa contador de falhas. Se atingir _MAX_RETRIES, grava na DLQ
    e publica evento system.task_failed no event bus.
    """
    key = f"{_FAIL_PREFIX}{task_name}:{job_id}"
    count = await redis.incr(key)
    await redis.expire(key, _DLQ_TTL)

    if count >= _MAX_RETRIES:
        await _send_to_dlq(redis, task_name, job_id, error, int(count))
        return True
    return False


async def _send_to_dlq(
    redis: aioredis.Redis,
    task_name: str,
    job_id: str,
    error: str,
    attempt: int,
) -> None:
    """Grava job na DLQ e publica evento de alerta."""
    entry = {
        "task": task_name,
        "job_id": job_id,
        "error": error,
        "attempt": attempt,
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }
    dlq_key = f"{_DLQ_PREFIX}{task_name}"
    await redis.lpush(dlq_key, json.dumps(entry))
    await redis.ltrim(dlq_key, 0, 999)  # guardar últimos 1000 por task
    await redis.expire(dlq_key, _DLQ_TTL)

    # Publicar evento no event bus para acionar NotificationRules
    try:
        from vms.infrastructure.messaging.event_bus import publish_event
        await publish_event(
            routing_key="system.task_failed",
            payload={
                "task": task_name,
                "job_id": job_id,
                "error": error,
                "attempt": attempt,
            },
        )
    except Exception as exc:
        logger.warning("Falha ao publicar system.task_failed: %s", exc)

    logger.error(
        "TASK DLQ: %s (job=%s) falhou %d vezes consecutivas. Erro: %s",
        task_name, job_id, attempt, error,
    )
