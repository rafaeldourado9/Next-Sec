"""Testes de resiliência de rede do VMSClient — ver ADR-017 §2/§3.

Simula queda de rede real via `httpx.MockTransport` (falha as primeiras N
chamadas, depois volta a funcionar) — o `VMSClient` de fato faz as chamadas
HTTP através do transporte substituído, não há mock do próprio cliente.
Verifica que:
- eventos que falham por erro de rede persistem na fila SQLite (`outbox.db`
  real em disco) e são reenviados com sucesso assim que a rede volta;
- eventos rejeitados por erro do próprio conteúdo (4xx) NÃO são reenfileirados;
- `list_cameras`/`list_rois`/`list_watchlist` retornam o cache last-known-good
  em vez de lista vazia quando a rede cai.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from analytics.core.config import get_settings
from analytics.core.vms_client import VMSClient

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    """Cada teste usa seu próprio arquivo SQLite e não bate em rede de verdade."""
    monkeypatch.setenv("OUTBOX_DB_PATH", str(tmp_path / "outbox.db"))
    monkeypatch.setenv("VMS_API_URL", "http://testserver")
    monkeypatch.setenv("EDGE_DEPLOYMENT", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FlakyEventsTransport(httpx.MockTransport):
    """Falha as primeiras `fail_times` chamadas de POST em /plugins/events com
    erro de conexão (simula queda passageira do túnel WireGuard do Nível 1),
    depois passa a responder 201 normalmente."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0
        super().__init__(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/plugins/events":
            self.calls += 1
            if self.calls <= self.fail_times:
                raise httpx.ConnectError("queda de rede simulada", request=request)
            return httpx.Response(201, json={"id": "evt-real-1", "status": "accepted"})
        return httpx.Response(404, json={"detail": "not found"})


class _RejectingEventsTransport(httpx.MockTransport):
    """Sempre responde 422 (erro de validação) — nunca deve ser reenfileirado."""

    def __init__(self) -> None:
        self.calls = 0
        super().__init__(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(422, json={"detail": "payload inválido"})


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    elapsed = 0.0
    while elapsed < timeout:
        if predicate():
            return True
        await asyncio.sleep(interval)
        elapsed += interval
    return predicate()


class TestIngestEventOutboxRetry:
    async def test_network_failure_queues_then_retries_successfully(self) -> None:
        transport = _FlakyEventsTransport(fail_times=2)
        client = VMSClient()
        await client.start(transport=transport, retry_poll_interval=0.05)
        try:
            ok = await client.ingest_event(
                camera_id="cam-1",
                event_type="intrusion.detected",
                payload={"class": "person"},
            )
            # Enfileirado com sucesso — chamador não precisa saber que ainda
            # não chegou de verdade na VPS.
            assert ok is True
            assert client._outbox.count_pending() == 1

            reached_empty = await _wait_until(lambda: client._outbox.count_pending() == 0)
            assert reached_empty, "outbox deveria esvaziar após a rede voltar"
            assert transport.calls >= 3  # 2 falhas + pelo menos 1 sucesso
        finally:
            await client.close()

    async def test_validation_error_is_not_queued_for_retry(self) -> None:
        transport = _RejectingEventsTransport()
        client = VMSClient()
        await client.start(transport=transport, retry_poll_interval=0.05)
        try:
            ok = await client.ingest_event(
                camera_id="cam-1", event_type="intrusion.detected", payload={},
            )
            assert ok is False
            assert client._outbox.count_pending() == 0

            # Dá um tempo pro loop rodar — não deve nada aparecer na fila.
            await asyncio.sleep(0.2)
            assert client._outbox.count_pending() == 0
            assert transport.calls == 1  # não reenfileirado, não retentado
        finally:
            await client.close()

    async def test_no_client_returns_false_without_enqueueing(self) -> None:
        client = VMSClient()  # start() nunca chamado
        ok = await client.ingest_event(camera_id="cam-1", event_type="x", payload={})
        assert ok is False
        assert client._outbox.count_pending() == 0


class _AlwaysDownTransport(httpx.MockTransport):
    """Nunca responde com sucesso — simula a VPS central fora do ar por um
    período prolongado (ex.: horas, não uma queda passageira) através do
    túnel WireGuard do Nível 1."""

    def __init__(self) -> None:
        self.calls = 0
        super().__init__(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        raise httpx.ConnectError("VPS inacessível", request=request)


class TestOutboxCap:
    """Cap de tamanho e idade da fila local (ADR-018 §5).

    Substitui `TestOutboxUnboundedGrowth`, que documentava a **ausência** de
    cap como limitação aceita da ADR-017 (relato em `.genesis/memory/
    progress.md`, Sprint 6). A premissa mudou: a ADR-018 vende o edge como algo
    que funciona offline sem prazo, e fila sem teto nesse cenário enche o disco
    do mini-PC do cliente — derrubando junto a gravação contínua, que é a
    função mais importante do equipamento.
    """

    async def test_oldest_events_are_dropped_when_the_queue_is_full(self) -> None:
        transport = _AlwaysDownTransport()
        client = VMSClient()
        # poll_interval alto: a VPS segue fora do ar, então a contagem só muda
        # por causa dos `ingest_event` que chegam, não por corrida com o retry.
        await client.start(transport=transport, retry_poll_interval=10.0)
        client._outbox._max_rows = 10
        try:
            for i in range(25):
                ok = await client.ingest_event(
                    camera_id=f"cam-{i:02d}", event_type="intrusion.detected", payload={"i": i},
                )
                assert ok is True  # enfileirado, do ponto de vista do chamador

            assert client._outbox.count_pending() == 10

            # Os 10 que sobraram são os mais RECENTES: com a fila cheia, o
            # cliente precisa preservar o que está acontecendo agora, não o
            # que aconteceu há dias.
            remaining = [p["body"]["camera_id"] for _, p, _ in client._outbox.list_due()]
            assert remaining == [f"cam-{i:02d}" for i in range(15, 25)]
        finally:
            await client.close()

    async def test_dropped_count_is_reported_and_then_reset(self) -> None:
        """Descarte silencioso seria o pior dos mundos — o heartbeat leva esse
        número pra VPS justamente pra o problema aparecer sem alguém precisar
        acessar a máquina do cliente."""
        transport = _AlwaysDownTransport()
        client = VMSClient()
        await client.start(transport=transport, retry_poll_interval=10.0)
        client._outbox._max_rows = 5
        try:
            for i in range(12):
                await client.ingest_event(
                    camera_id=f"cam-{i}", event_type="intrusion.detected", payload={},
                )

            assert client._outbox.drain_dropped_count() == 7
            # Drenar zera: o heartbeat reporta um delta, não um acumulado.
            assert client._outbox.drain_dropped_count() == 0
        finally:
            await client.close()

    async def test_events_older_than_the_age_limit_are_dropped(self) -> None:
        transport = _AlwaysDownTransport()
        client = VMSClient()
        await client.start(transport=transport, retry_poll_interval=10.0)
        client._outbox._max_age_seconds = 0  # tudo já nasce "velho demais"
        try:
            await client.ingest_event(
                camera_id="cam-antiga", event_type="intrusion.detected", payload={},
            )
            assert client._outbox.count_pending() == 0
            assert client._outbox.drain_dropped_count() == 1
        finally:
            await client.close()

    async def test_queue_stays_bounded_but_intact_below_the_cap(self) -> None:
        """O cap não pode virar perda de evento em operação normal."""
        transport = _AlwaysDownTransport()
        client = VMSClient()
        await client.start(transport=transport, retry_poll_interval=10.0)
        client._outbox._max_rows = 100
        try:
            for i in range(30):
                await client.ingest_event(
                    camera_id=f"cam-{i}", event_type="intrusion.detected", payload={},
                )
            assert client._outbox.count_pending() == 30
            assert client._outbox.drain_dropped_count() == 0
        finally:
            await client.close()


class _ThrottlingTransport(httpx.MockTransport):
    """Responde 429 com `Retry-After` até `stop_throttling` virar True."""

    def __init__(self, retry_after: str = "12") -> None:
        self.retry_after = retry_after
        self.calls = 0
        self.throttling = True
        super().__init__(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.throttling:
            return httpx.Response(
                429, json={"detail": "cota excedida"}, headers={"Retry-After": self.retry_after}
            )
        return httpx.Response(201, json={"id": "evt-1", "status": "accepted"})


class TestBackpressure:
    """Resposta ao `429 + Retry-After` da VPS (ADR-018 §5).

    Sem isso, um cliente sob cota estourada continuaria no backoff dele — que
    é curto de propósito pra falha de rede — e transformaria uma recusa
    educada num ataque acidental contra a VPS compartilhada.
    """

    async def test_429_is_queued_not_discarded(self) -> None:
        """429 é um 4xx que, ao contrário dos outros, precisa ser reenfileirado:
        não há nada errado com o evento, só com o ritmo."""
        transport = _ThrottlingTransport()
        client = VMSClient()
        await client.start(transport=transport, retry_poll_interval=10.0)
        try:
            ok = await client.ingest_event(
                camera_id="cam-1", event_type="intrusion.detected", payload={},
            )
            assert ok is True
            assert client._outbox.count_pending() == 1
        finally:
            await client.close()

    async def test_429_defers_the_whole_queue(self) -> None:
        """Adiar só o item que tomou 429 faria o próximo bater na mesma parede
        um instante depois, gastando uma tentativa de cada item pra descobrir
        o que a VPS já disse uma vez."""
        transport = _ThrottlingTransport(retry_after="30")
        client = VMSClient()
        await client.start(transport=transport, retry_poll_interval=10.0)
        try:
            for i in range(5):
                await client.ingest_event(
                    camera_id=f"cam-{i}", event_type="intrusion.detected", payload={},
                )
            assert client._outbox.count_pending() == 5
            # Fila adiada: nada vencido agora, apesar de todos terem acabado
            # de ser enfileirados (que normalmente ficam devidos na hora).
            assert client._outbox.list_due() == []
        finally:
            await client.close()

    async def test_absurd_retry_after_is_capped(self) -> None:
        """Um `Retry-After` disparatado (bug da VPS ou proxy hostil no meio)
        congelaria a fila do cliente por horas sem ninguém perceber."""
        transport = _ThrottlingTransport(retry_after="999999")
        client = VMSClient()
        await client.start(transport=transport, retry_poll_interval=10.0)
        try:
            await client.ingest_event(
                camera_id="cam-1", event_type="intrusion.detected", payload={},
            )
            import time as _time

            with client._outbox._connect() as conn:
                next_attempt = conn.execute(
                    "SELECT next_attempt_at FROM pending_events"
                ).fetchone()[0]
            assert next_attempt - _time.time() <= 900 + 1
        finally:
            await client.close()

    async def test_queue_drains_once_the_quota_frees_up(self) -> None:
        transport = _ThrottlingTransport(retry_after="1")
        client = VMSClient()
        await client.start(transport=transport, retry_poll_interval=0.05)
        try:
            for i in range(3):
                await client.ingest_event(
                    camera_id=f"cam-{i}", event_type="intrusion.detected", payload={},
                )
            assert client._outbox.count_pending() == 3

            transport.throttling = False
            drained = await _wait_until(
                lambda: client._outbox.count_pending() == 0, timeout=10.0
            )
            assert drained, "fila deveria escoar assim que a cota liberasse"
        finally:
            await client.close()

    async def test_backlog_fully_drains_without_loss_or_duplication_once_network_recovers(
        self,
    ) -> None:
        """Ainda que sem cap, a fila precisa continuar íntegra: quando a
        rede volta depois de um backlog considerável, todos os eventos são
        reenviados — nenhum perdido, nenhum duplicado.

        Não exige ordem estrita de chegada (achado durante a auditoria de
        S6-06, ao rodar isto com uma queda de rede real): `reschedule()`
        (outbox.py) agenda `next_attempt_at` com backoff por item a partir
        do instante da SUA própria falha, não de um relógio global — então
        sob falha concorrente de vários itens, os que erraram por último
        (menos tentativas acumuladas) podem ficar "devidos" antes dos que
        erraram primeiro, e `run_retry_loop` reenvia fora da ordem de
        enfileiramento. Isso é aceitável: cada evento carrega seu próprio
        `occurred_at` (ver `Orchestrator._analytics_loop` em
        `core/orchestrator.py`, `result.occurred_at.isoformat()`) — é essa
        marca de tempo, não a ordem de chegada na API, que a VMS usa pra
        ordenar a timeline de eventos (`api/src/vms/events/repository.py`).
        Perda ou duplicação, sim, seriam bugs reais; ordem de entrega não é
        uma garantia que o sistema precisa (nem oferece)."""
        received: list[str] = []
        down = {"value": True}

        def handler(request: httpx.Request) -> httpx.Response:
            if down["value"]:
                raise httpx.ConnectError("VPS inacessível", request=request)
            body = json.loads(request.content)
            received.append(body["camera_id"])
            return httpx.Response(201, json={"id": f"evt-{body['camera_id']}"})

        transport = httpx.MockTransport(handler)
        client = VMSClient()
        await client.start(transport=transport, retry_poll_interval=0.05)
        try:
            n_events = 20
            expected = [f"cam-{i:02d}" for i in range(n_events)]
            for camera_id in expected:
                await client.ingest_event(
                    camera_id=camera_id, event_type="intrusion.detected", payload={},
                )
            assert client._outbox.count_pending() == n_events

            down["value"] = False  # VPS volta ao ar
            reached_empty = await _wait_until(
                lambda: client._outbox.count_pending() == 0, timeout=10.0
            )
            assert reached_empty, "backlog inteiro deveria escoar quando a rede volta"
            assert sorted(received) == sorted(expected), "nenhum evento perdido ou duplicado"
        finally:
            await client.close()


class TestLastKnownGoodCache:
    async def test_list_cameras_falls_back_to_cache_on_network_error(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(200, json=[{"id": "cam-1", "name": "Entrada"}])
            raise httpx.ConnectError("queda de rede simulada", request=request)

        transport = httpx.MockTransport(handler)
        client = VMSClient()
        await client.start(transport=transport, retry_poll_interval=10.0)
        try:
            first = await client.list_cameras()
            assert first == [{"id": "cam-1", "name": "Entrada"}]

            second = await client.list_cameras()
            assert second == first  # cache last-known-good, não lista vazia
        finally:
            await client.close()

    async def test_list_cameras_returns_empty_when_never_succeeded(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("sempre fora do ar", request=request)

        client = VMSClient()
        await client.start(transport=httpx.MockTransport(handler), retry_poll_interval=10.0)
        try:
            result = await client.list_cameras()
            assert result == []
        finally:
            await client.close()

    async def test_list_rois_cache_is_keyed_by_camera_id(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            camera_id = request.url.params.get("camera_id")
            if camera_id == "cam-1":
                return httpx.Response(200, json=[{"id": "roi-1"}])
            raise httpx.ConnectError("queda de rede simulada", request=request)

        client = VMSClient()
        await client.start(transport=httpx.MockTransport(handler), retry_poll_interval=10.0)
        try:
            ok = await client.list_rois("cam-1")
            assert ok == [{"id": "roi-1"}]

            # cam-2 nunca teve sucesso — cache vazio, não o de cam-1
            other = await client.list_rois("cam-2")
            assert other == []

            # cam-1 continua servindo do cache mesmo com a rede caindo agora
            cached_again = await client.list_rois("cam-1")
            assert cached_again == [{"id": "roi-1"}]
        finally:
            await client.close()
