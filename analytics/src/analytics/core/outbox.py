"""Fila de retry durável (SQLite) para eventos que falharam ao enviar à VMS API central.

Ver ADR-017 §2: decisão de usar SQLite (stdlib `sqlite3`, sem dependência
nova) em vez de Postgres local no `docker-compose.edge.yml` — o único
requisito real do Nível 1 é uma fila durável simples que sobreviva a um
reinício do container enquanto a VPS central está inacessível (túnel
WireGuard fora do ar), não um schema relacional completo.

**Cap de tamanho e idade (ADR-018 §5).** Até a ADR-017 a fila crescia sem
limite, o que era aceitável enquanto o caso motivador era "queda passageira de
rede" (limitação registrada em `docs/DEPLOY_EDGE.md` §7 e coberta por
`tests/test_vms_client_resilience.py`). A ADR-018 muda a premissa: o edge passa
a ser vendido como algo que "funciona offline", sem prazo definido para a rede
voltar. Fila sem cap, nesse cenário, é uma bomba-relógio — enche o disco do
mini-PC do cliente e derruba junto a gravação contínua, que é a função mais
importante do equipamento. O descarte agora é explícito, pelos itens mais
antigos, e contado para o heartbeat reportar à VPS.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Backoff exponencial simples: 5s, 10s, 20s, 40s... com teto de 5min — ver
# ADR-017 §2. Evita martelar a VPS central durante uma queda prolongada do
# túnel, mas ainda tenta reconectar rápido o suficiente numa queda passageira.
_INITIAL_BACKOFF_SECONDS = 5
_MAX_BACKOFF_SECONDS = 300
_DEFAULT_POLL_INTERVAL_SECONDS = 5.0

# Defaults do cap. 50 000 eventos ≈ 25 MB de `outbox.db` no pior caso (payload
# de evento é JSON pequeno; snapshot e clipe ficam fora, só o path viaja aqui)
# e 7 dias cobre com folga qualquer queda de rede que ainda valha a pena
# reenviar — evento de intrusão de duas semanas atrás não tem valor
# operacional, só custo de banda quando a rede volta.
_DEFAULT_MAX_ROWS = 50_000
_DEFAULT_MAX_AGE_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class SendOutcome:
    """Resultado de uma tentativa de envio feita pelo `sender` do retry loop.

    Existe para o `sender` conseguir dizer *"a VPS me pediu para esperar N
    segundos"* (HTTP 429 + `Retry-After`, ver ADR-018 §5) — informação que um
    simples `False` não carrega. Sem isso, um edge sob cota estourada
    continuaria batendo no backoff dele, que é curto de propósito para falhas
    de rede, e transformaria uma recusa educada num ataque acidental.
    """

    delivered: bool
    retry_after_seconds: int | None = None


class EventOutbox:
    """Fila de retry persistida em SQLite para envios que falharam por erro de rede.

    Cada linha guarda o payload serializado (JSON) do envio que falhou, o
    número de tentativas já feitas e o timestamp (epoch, `time.time()`) da
    próxima tentativa permitida. `sqlite3` é síncrono — os métodos desta
    classe também são; o chamador assíncrono deve envolvê-los com
    `asyncio.to_thread` (ver `run_retry_loop` abaixo e `VMSClient`).
    """

    def __init__(
        self,
        db_path: str,
        max_rows: int = _DEFAULT_MAX_ROWS,
        max_age_seconds: int = _DEFAULT_MAX_AGE_SECONDS,
    ) -> None:
        self._db_path = db_path
        self._max_rows = max_rows
        self._max_age_seconds = max_age_seconds
        # Acumulado desde o último `drain_dropped_count()` — o heartbeat leva
        # esse número pra VPS. Descarte silencioso seria o pior dos mundos: o
        # cliente perde evento e ninguém fica sabendo.
        self._dropped = 0
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
        passada do loop). Retorna o ID da linha criada.

        Aplica o cap logo após inserir: o item novo é sempre aceito e, se
        preciso, o mais antigo é que sai. Descartar o recém-chegado seria pior
        — significaria que, com a fila cheia, o cliente pararia de registrar o
        que está acontecendo agora para preservar o que aconteceu há dias.
        """
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO pending_events "
                "(payload_json, attempts, next_attempt_at, created_at) VALUES (?, 0, ?, ?)",
                (json.dumps(payload), now, now),
            )
            row_id = int(cur.lastrowid)
        self._prune()
        return row_id

    def list_due(self, limit: int | None = None) -> list[tuple[int, dict[str, Any], int]]:
        """Retorna `(id, payload, attempts)` das linhas cujo backoff já venceu."""
        now = time.time()
        sql = (
            "SELECT id, payload_json, attempts FROM pending_events "
            "WHERE next_attempt_at <= ? ORDER BY id ASC"
        )
        args: tuple[Any, ...] = (now,)
        if limit is not None:
            sql += " LIMIT ?"
            args = (now, limit)
        with self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [(row["id"], json.loads(row["payload_json"]), row["attempts"]) for row in rows]

    def remove(self, row_id: int) -> None:
        """Remove a linha — chamado após reenvio confirmado com sucesso."""
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_events WHERE id = ?", (row_id,))

    def reschedule(self, row_id: int, attempts: int) -> None:
        """Agenda a próxima tentativa com backoff exponencial (5s, 10s, 20s... teto 5min)."""
        backoff = min(_INITIAL_BACKOFF_SECONDS * (2**attempts), _MAX_BACKOFF_SECONDS)
        self._set_next_attempt(row_id, attempts + 1, time.time() + backoff)

    def defer_all(self, seconds: int) -> None:
        """Adia TODA a fila — resposta a um `Retry-After` da VPS (ADR-018 §5).

        Coletivo de propósito: a cota é por tenant, não por evento. Adiar só o
        item que tomou 429 faria o próximo da fila bater na mesma parede um
        instante depois, gastando uma tentativa de cada item para descobrir o
        que a VPS já disse uma vez. Não incrementa `attempts` — não é falha do
        item, e contar como tal aceleraria o backoff dele sem motivo.
        """
        until = time.time() + max(seconds, 1)
        with self._connect() as conn:
            conn.execute(
                "UPDATE pending_events SET next_attempt_at = ? WHERE next_attempt_at < ?",
                (until, until),
            )

    def count_pending(self) -> int:
        """Total de linhas ainda na fila (independente de estarem vencidas ou não)."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM pending_events").fetchone()
            return int(row["c"])

    def drain_dropped_count(self) -> int:
        """Quantos itens o cap descartou desde a última chamada, zerando o contador.

        Consumido pelo heartbeat (`outbox_dropped`): é o sinal de que este
        cliente está perdendo evento de verdade — ou a rede dele não sustenta o
        volume, ou a cota está apertada demais para o caso de uso.
        """
        dropped, self._dropped = self._dropped, 0
        return dropped

    def _prune(self) -> None:
        """Aplica cap de idade e de tamanho, nessa ordem."""
        with self._connect() as conn:
            by_age = conn.execute(
                "DELETE FROM pending_events WHERE created_at < ?",
                (time.time() - self._max_age_seconds,),
            ).rowcount

            # `id` é AUTOINCREMENT: ordenar por ele é ordenar por antiguidade,
            # sem depender de `created_at` (que pode empatar em rajada).
            by_size = conn.execute(
                "DELETE FROM pending_events WHERE id IN ("
                "  SELECT id FROM pending_events ORDER BY id ASC"
                "  LIMIT MAX(0, (SELECT COUNT(*) FROM pending_events) - ?)"
                ")",
                (self._max_rows,),
            ).rowcount

        dropped = max(by_age, 0) + max(by_size, 0)
        if dropped:
            self._dropped += dropped
            logger.warning(
                "Outbox: %d evento(s) descartado(s) pelo cap (idade=%d tamanho=%d) — "
                "fila em %d itens, teto de %d",
                dropped, max(by_age, 0), max(by_size, 0), self.count_pending(), self._max_rows,
            )

    def _set_next_attempt(self, row_id: int, attempts: int, next_attempt_at: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE pending_events SET attempts = ?, next_attempt_at = ? WHERE id = ?",
                (attempts, next_attempt_at, row_id),
            )


async def run_retry_loop(
    outbox: EventOutbox,
    sender: Callable[[dict[str, Any]], Awaitable[bool | SendOutcome]],
    poll_interval: float = _DEFAULT_POLL_INTERVAL_SECONDS,
) -> None:
    """Loop assíncrono de background: tenta reenviar payloads pendentes vencidos.

    `sender` é uma coroutine que faz o envio de fato (POST/PUT real) e retorna
    `True`/`False` ou um `SendOutcome` — desacoplada do transporte HTTP
    concreto para poder ser testada isoladamente (ver
    `analytics/tests/test_vms_client_resilience.py`). O retorno booleano
    continua aceito para não obrigar todo chamador a conhecer o `SendOutcome`.
    Roda até ser cancelado (`asyncio.CancelledError`) — ver `VMSClient.start()`/
    `close()`, que criam/cancelam esta task.
    """
    while True:
        try:
            due = await asyncio.to_thread(outbox.list_due)
            for row_id, payload, attempts in due:
                outcome = _as_outcome(await sender(payload))

                if outcome.delivered:
                    await asyncio.to_thread(outbox.remove, row_id)
                    logger.info("Outbox: item %d reenviado com sucesso", row_id)
                    continue

                if outcome.retry_after_seconds:
                    # A VPS pediu para esperar: para a passada inteira em vez
                    # de tentar o próximo item — ele tomaria a mesma recusa.
                    await asyncio.to_thread(outbox.defer_all, outcome.retry_after_seconds)
                    logger.warning(
                        "Outbox: VPS pediu backpressure — fila adiada por %ds",
                        outcome.retry_after_seconds,
                    )
                    break

                await asyncio.to_thread(outbox.reschedule, row_id, attempts)
                logger.warning(
                    "Outbox: item %d ainda falhando (tentativa %d)", row_id, attempts + 1
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erro no loop de retry do outbox — nova tentativa no próximo ciclo")
        await asyncio.sleep(poll_interval)


def _as_outcome(result: bool | SendOutcome) -> SendOutcome:
    """Normaliza o retorno do `sender` (bool legado ou `SendOutcome`)."""
    if isinstance(result, SendOutcome):
        return result
    return SendOutcome(delivered=bool(result))
