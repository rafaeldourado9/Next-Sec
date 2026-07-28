"""Fila de retry durável (SQLite) para eventos que falharam ao enviar à VMS API central.

Ver ADR-017 §2: decisão de usar SQLite (stdlib `sqlite3`, sem dependência
nova) em vez de Postgres local no `docker-compose.edge.yml` — o único
requisito real do Nível 1 é uma fila durável simples que sobreviva a um
reinício do container enquanto a VPS central está inacessível (túnel
WireGuard fora do ar), não um schema relacional completo.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Backoff exponencial simples: 5s, 10s, 20s, 40s... com teto de 5min — ver
# ADR-017 §2. Evita martelar a VPS central durante uma queda prolongada do
# túnel, mas ainda tenta reconectar rápido o suficiente numa queda passageira.
_INITIAL_BACKOFF_SECONDS = 5
_MAX_BACKOFF_SECONDS = 300
_DEFAULT_POLL_INTERVAL_SECONDS = 5.0


class EventOutbox:
    """Fila de retry persistida em SQLite para envios que falharam por erro de rede.

    Cada linha guarda o payload serializado (JSON) do envio que falhou, o
    número de tentativas já feitas e o timestamp (epoch, `time.time()`) da
    próxima tentativa permitida. `sqlite3` é síncrono — os métodos desta
    classe também são; o chamador assíncrono deve envolvê-los com
    `asyncio.to_thread` (ver `run_retry_loop` abaixo e `VMSClient`).
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        parent = Path(db_path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload_json TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    def enqueue(self, payload: dict[str, Any]) -> int:
        """Grava um payload pendente, disponível para retry imediato (próxima
        passada do loop). Retorna o ID da linha criada."""
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO pending_events "
                "(payload_json, attempts, next_attempt_at, created_at) VALUES (?, 0, ?, ?)",
                (json.dumps(payload), now, now),
            )
            return int(cur.lastrowid)

    def list_due(self) -> list[tuple[int, dict[str, Any], int]]:
        """Retorna `(id, payload, attempts)` das linhas cujo backoff já venceu."""
        now = time.time()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, payload_json, attempts FROM pending_events "
                "WHERE next_attempt_at <= ? ORDER BY id ASC",
                (now,),
            ).fetchall()
        return [(row["id"], json.loads(row["payload_json"]), row["attempts"]) for row in rows]

    def remove(self, row_id: int) -> None:
        """Remove a linha — chamado após reenvio confirmado com sucesso."""
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_events WHERE id = ?", (row_id,))

    def reschedule(self, row_id: int, attempts: int) -> None:
        """Agenda a próxima tentativa com backoff exponencial (5s, 10s, 20s... teto 5min)."""
        backoff = min(_INITIAL_BACKOFF_SECONDS * (2**attempts), _MAX_BACKOFF_SECONDS)
        next_attempt_at = time.time() + backoff
        with self._connect() as conn:
            conn.execute(
                "UPDATE pending_events SET attempts = ?, next_attempt_at = ? WHERE id = ?",
                (attempts + 1, next_attempt_at, row_id),
            )

    def count_pending(self) -> int:
        """Total de linhas ainda na fila (independente de estarem vencidas ou não)."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM pending_events").fetchone()
            return int(row["c"])


async def run_retry_loop(
    outbox: EventOutbox,
    sender: Callable[[dict[str, Any]], Awaitable[bool]],
    poll_interval: float = _DEFAULT_POLL_INTERVAL_SECONDS,
) -> None:
    """Loop assíncrono de background: tenta reenviar payloads pendentes vencidos.

    `sender` é uma coroutine que faz o envio de fato (POST/PUT real) e
    retorna `True`/`False` — desacoplada do transporte HTTP concreto para
    poder ser testada isoladamente (ver `analytics/tests/test_vms_client_
    resilience.py`). Roda até ser cancelado (`asyncio.CancelledError`) — ver
    `VMSClient.start()`/`close()`, que criam/cancelam esta task.
    """
    while True:
        try:
            due = await asyncio.to_thread(outbox.list_due)
            for row_id, payload, attempts in due:
                ok = await sender(payload)
                if ok:
                    await asyncio.to_thread(outbox.remove, row_id)
                    logger.info("Outbox: item %d reenviado com sucesso", row_id)
                else:
                    await asyncio.to_thread(outbox.reschedule, row_id, attempts)
                    logger.warning(
                        "Outbox: item %d ainda falhando (tentativa %d)", row_id, attempts + 1
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erro no loop de retry do outbox — nova tentativa no próximo ciclo")
        await asyncio.sleep(poll_interval)
