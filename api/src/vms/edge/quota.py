"""Cota de ingestão por tenant — token bucket no Redis (ADR-018 §5).

Por que token bucket e não o `slowapi` que já existe no projeto: o `limiter`
global tem chave por IP (`get_remote_address`) e janela fixa. Aqui a chave
precisa ser o **tenant** (um cliente com IP dinâmico não pode escapar da cota,
e vários clientes atrás do mesmo CGNAT não podem dividir uma), e o custo de um
request é variável (um lote de 80 eventos consome 80 tokens, não 1). Janela
fixa também deixaria passar 2x o limite na virada da janela — com bucket, o
burst é explícito e limitado.

O script Lua roda os dois passos (ler+debitar) atomicamente: sem isso, dois
workers da API atendendo lotes do mesmo tenant ao mesmo tempo leriam o mesmo
saldo e ambos passariam.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Burst = 2 minutos de cota. Gravação de evento é naturalmente irregular (um
# carro entrando dispara vários eventos em segundos, depois nada por horas) —
# um bucket sem folga recusaria rajadas legítimas de um cliente que está muito
# abaixo da média contratada.
_BURST_MULTIPLIER = 2

# KEYS[1] = chave do bucket
# ARGV[1] = capacidade (tokens)   ARGV[2] = taxa de recarga (tokens/segundo)
# ARGV[3] = custo desta chamada   ARGV[4] = timestamp atual (segundos, float)
_TOKEN_BUCKET_LUA = """
local bucket = redis.call('HMGET', KEYS[1], 'tokens', 'updated_at')
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

local tokens = tonumber(bucket[1])
local updated_at = tonumber(bucket[2])
if tokens == nil then
    tokens = capacity
    updated_at = now
end

tokens = math.min(capacity, tokens + (now - updated_at) * refill_rate)

local allowed = 0
if tokens >= cost then
    allowed = 1
    tokens = tokens - cost
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_at', now)
-- TTL generoso: a chave só precisa sobreviver ao tempo de recarga completa.
-- Um tenant inativo some do Redis sozinho, sem rotina de limpeza.
redis.call('EXPIRE', KEYS[1], math.ceil(capacity / refill_rate) + 60)

local retry_after = 0
if allowed == 0 then
    retry_after = math.ceil((cost - tokens) / refill_rate)
end

return {allowed, math.floor(tokens), retry_after}
"""


@dataclass(frozen=True)
class QuotaDecision:
    """Resultado de uma checagem de cota."""

    allowed: bool
    remaining: int
    retry_after_seconds: int


class IngestQuota:
    """Token bucket por tenant sobre o Redis da API."""

    def __init__(self, redis_client) -> None:  # noqa: ANN001 — redis.asyncio.Redis
        self._redis = redis_client
        self._script = None

    async def check(
        self, tenant_id: str, events_per_minute: int, cost: int
    ) -> QuotaDecision:
        """Debita `cost` tokens do bucket do tenant.

        **Falha aberta**: se o Redis estiver indisponível, libera a requisição
        em vez de recusá-la. Cota é proteção contra abuso, não um controle de
        integridade — derrubar a ingestão de todos os clientes porque o Redis
        piscou seria trocar um problema hipotético por uma perda real de
        eventos (o edge tem outbox, mas com cap: perda prolongada vira
        descarte). O incidente do Redis fica visível no log.
        """
        capacity = max(events_per_minute * _BURST_MULTIPLIER, cost)
        refill_rate = events_per_minute / 60.0

        try:
            if self._script is None:
                self._script = self._redis.register_script(_TOKEN_BUCKET_LUA)
            allowed, remaining, retry_after = await self._script(
                keys=[f"edge:quota:{tenant_id}"],
                args=[capacity, refill_rate, cost, time.time()],
            )
        except Exception:
            logger.exception(
                "Redis indisponível na checagem de cota do tenant %s — liberando request", tenant_id
            )
            return QuotaDecision(allowed=True, remaining=-1, retry_after_seconds=0)

        return QuotaDecision(
            allowed=bool(allowed),
            remaining=int(remaining),
            # Nunca devolve 0: um `Retry-After: 0` faria o agente reenviar
            # imediatamente e queimar a tentativa de novo.
            retry_after_seconds=max(int(retry_after), 1),
        )
