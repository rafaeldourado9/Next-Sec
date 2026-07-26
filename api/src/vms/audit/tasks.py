"""Tasks ARQ para manutenção da tabela audit_log particionada."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from vms.infrastructure.database.connection import get_db_context

logger = logging.getLogger(__name__)

_MONTHS_AHEAD = 3  # cria partições para os próximos 3 meses


def _partition_range(year: int, month: int) -> tuple[str, str]:
    """Retorna (start, end) no formato 'YYYY-MM-DD' para a partição do mês."""
    start = f"{year}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1}-01-01"
    else:
        end = f"{year}-{month + 1:02d}-01"
    return start, end


def _partition_name(year: int, month: int) -> str:
    return f"audit_log_{year}_{month:02d}"


async def task_ensure_audit_partitions(ctx: dict) -> dict:
    """Garante que existam partições mensais do audit_log para os próximos meses.

    Roda todo dia 1 do mês às 00:01 UTC via ARQ cron.
    Cria partições para _MONTHS_AHEAD meses à frente, sem falhar se já existirem.
    """
    now = datetime.now(UTC)
    created: list[str] = []
    skipped: list[str] = []

    async with get_db_context() as session:
        for offset in range(_MONTHS_AHEAD + 1):
            target = now.replace(day=1) + timedelta(days=32 * offset)
            target = target.replace(day=1)
            year, month = target.year, target.month

            name = _partition_name(year, month)
            start, end = _partition_range(year, month)

            # Valores calculados internamente — sem risco de SQL injection
            sql = text(
                f"CREATE TABLE IF NOT EXISTS {name}"
                f" PARTITION OF audit_log"
                f" FOR VALUES FROM ('{start}') TO ('{end}')"
            )

            try:
                await session.execute(sql)
                created.append(name)
            except Exception as exc:
                logger.warning("Partição %s: %s", name, exc)
                skipped.append(name)

    logger.info(
        "ensure_audit_partitions: criadas=%s skipped=%s",
        created,
        skipped,
    )
    return {"created": created, "skipped": skipped}
