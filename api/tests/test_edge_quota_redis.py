"""Token bucket de cota de ingestão contra um Redis REAL (ADR-018 §5).

Separado das demais suítes porque o coração da cota é um script Lua — ele não
roda em SQLite nem contra um fake, e é justamente a parte com maior risco de
estar sutilmente errada (aritmética de recarga, atomicidade, TTL). Testar só o
router com a decisão mockada verificaria o `if`, não o mecanismo.

Pulado quando `EDGE_QUOTA_TEST_REDIS_URL` não está definido, para não exigir
infra de quem só roda a suíte unitária:

    docker run -d --name redis-test -p 56379:6379 redis:7-alpine
    EDGE_QUOTA_TEST_REDIS_URL=redis://127.0.0.1:56379/0 pytest tests/test_edge_quota_redis.py
"""
from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio

from vms.edge.quota import IngestQuota

_REDIS_URL = os.getenv("EDGE_QUOTA_TEST_REDIS_URL")

pytestmark = pytest.mark.integration

# Só as classes que falam com Redis são puladas — o teste de fail-open abaixo
# não precisa de infra nenhuma e não pode ficar refém dela.
_requires_redis = pytest.mark.skipif(
    not _REDIS_URL, reason="EDGE_QUOTA_TEST_REDIS_URL não definida"
)


@pytest_asyncio.fixture
async def quota():
    import redis.asyncio as aioredis

    client = aioredis.from_url(_REDIS_URL, decode_responses=False)
    await client.flushdb()
    yield IngestQuota(client)
    await client.aclose()


@_requires_redis
class TestTokenBucket:
    async def test_allows_within_capacity_and_reports_remaining(self, quota: IngestQuota) -> None:
        # 60 eventos/min → capacidade 120 (burst de 2 min), recarga de 1/s.
        decision = await quota.check("t1", events_per_minute=60, cost=10)

        assert decision.allowed
        assert decision.remaining == 110

    async def test_refuses_once_the_bucket_is_drained(self, quota: IngestQuota) -> None:
        await quota.check("t1", events_per_minute=60, cost=120)
        decision = await quota.check("t1", events_per_minute=60, cost=10)

        assert not decision.allowed
        # Nunca 0: um `Retry-After: 0` faria o agente reenviar na hora e
        # queimar a tentativa de novo.
        assert decision.retry_after_seconds >= 1

    async def test_tenants_do_not_share_a_bucket(self, quota: IngestQuota) -> None:
        """O ponto inteiro da cota: um cliente em loop de detecção não pode
        derrubar a ingestão dos outros."""
        await quota.check("noisy", events_per_minute=60, cost=120)
        assert not (await quota.check("noisy", events_per_minute=60, cost=5)).allowed

        assert (await quota.check("quiet", events_per_minute=60, cost=5)).allowed

    async def test_bucket_refills_over_time(self, quota: IngestQuota) -> None:
        await quota.check("t1", events_per_minute=60, cost=120)
        await asyncio.sleep(2.2)

        assert (await quota.check("t1", events_per_minute=60, cost=2)).allowed

    async def test_batch_larger_than_nominal_capacity_still_passes(
        self, quota: IngestQuota
    ) -> None:
        """Senão um cliente com cota apertada e um lote grande travaria pra
        sempre: nenhuma recarga jamais alcançaria o custo."""
        assert (await quota.check("t3", events_per_minute=10, cost=100)).allowed

    async def test_bucket_key_expires_on_its_own(self, quota: IngestQuota) -> None:
        """Sem TTL, cada tenant que já existiu deixaria lixo permanente no Redis."""
        import redis.asyncio as aioredis

        await quota.check("t1", events_per_minute=60, cost=1)
        client = aioredis.from_url(_REDIS_URL, decode_responses=False)
        ttl = await client.ttl("edge:quota:t1")
        await client.aclose()

        assert ttl > 0


class TestFailOpen:
    async def test_redis_down_allows_the_request(self) -> None:
        """Cota é proteção contra abuso, não controle de integridade: derrubar
        a ingestão de todos porque o Redis piscou trocaria um problema
        hipotético por perda real de eventos."""

        class _BrokenRedis:
            def register_script(self, _script: str):
                raise ConnectionError("Redis fora do ar (simulado)")

        decision = await IngestQuota(_BrokenRedis()).check("t1", 60, cost=10)

        assert decision.allowed
        assert decision.remaining == -1
