"""Reação do agente à credencial revogada e à policy do heartbeat (ADR-018).

Antes da ADR-018 a API key vinha num arquivo e valia para sempre — não havia
caminho pelo qual o agente descobrisse que deixou de ter direito ao serviço.
Agora a licença é revogável, e estes testes garantem os dois lados disso: o
agente **para** quando a credencial morre (em vez de reconectar em silêncio
para sempre) e **se reconfigura** quando os limites mudam no painel.
"""
from __future__ import annotations

import httpx
import pytest

from agent.cloud_client import CloudClient, CredentialsRevokedError
from agent.config import Settings


def _settings() -> Settings:
    return Settings(
        agent_id="agent-1",
        agent_api_key="vms_chave",
        vms_api_url="http://vps.exemplo.com",
    )


async def _client_with(handler) -> CloudClient:
    client = CloudClient(_settings())
    await client.start()
    # Substitui o transporte depois do start() pra não duplicar a montagem de
    # base_url/headers que o próprio CloudClient faz.
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url="http://vps.exemplo.com",
        headers={"Authorization": "ApiKey vms_chave"},
        transport=httpx.MockTransport(handler),
    )
    return client


class TestRevokedCredentials:
    async def test_config_401_raises_revoked(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "API key inválida ou revogada"})

        client = await _client_with(handler)
        try:
            with pytest.raises(CredentialsRevokedError):
                await client.get_config()
        finally:
            await client.stop()

    async def test_heartbeat_401_raises_revoked(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "revogada"})

        client = await _client_with(handler)
        try:
            with pytest.raises(CredentialsRevokedError):
                await client.send_edge_heartbeat(agent_version="1.0.0")
        finally:
            await client.stop()

    async def test_server_error_is_not_treated_as_revoked(self) -> None:
        """500 é a VPS com problema, não a licença — parar o agente por isso
        deixaria o cliente sem gravação por um incidente do outro lado."""
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "indisponível"})

        client = await _client_with(handler)
        try:
            assert await client.send_edge_heartbeat(agent_version="1.0.0") is None
        finally:
            await client.stop()


class TestEdgeHeartbeat:
    async def test_returns_the_policy(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "policy": {"clip_seconds": 25, "events_per_minute": 300},
                "license_status": "active",
            })

        client = await _client_with(handler)
        try:
            result = await client.send_edge_heartbeat(agent_version="1.0.0", cameras_online=3)
        finally:
            await client.stop()

        assert result["policy"]["clip_seconds"] == 25
        assert result["license_status"] == "active"

    async def test_sends_the_reported_stats(self) -> None:
        captured: dict = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured.update(json.loads(request.content))
            return httpx.Response(200, json={"policy": {}, "license_status": "active"})

        client = await _client_with(handler)
        try:
            await client.send_edge_heartbeat(
                agent_version="1.0.0", cameras_online=2, outbox_pending=17
            )
        finally:
            await client.stop()

        # `outbox_pending` é o sintoma mais útil que a VPS tem de um edge com
        # problema — ela não consegue olhar lá dentro.
        assert captured["outbox_pending"] == 17
        assert captured["cameras_online"] == 2

    async def test_network_failure_returns_none_instead_of_raising(self) -> None:
        """Heartbeat perdido não pode parar o processamento de câmera — o
        agente segue com a última policy que conhece."""
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("rede fora", request=request)

        client = await _client_with(handler)
        try:
            assert await client.send_edge_heartbeat(agent_version="1.0.0") is None
        finally:
            await client.stop()
