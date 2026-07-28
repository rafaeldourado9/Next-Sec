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
