"""`CloudClient.get_config()` — path do MediaMTX, não URL RTMP completa.

Bug real de produção (2026-08-02, primeiro teste ponta a ponta de um agent
nativo Windows publicando de verdade): a resposta de `GET /agents/me/config`
mandava `rtmp_push_url` já como URL RTMP **completa** (host interno da VPS
embutido), e este parsing tratava o valor como se fosse só um path — o
`StreamManager` prefixava a própria base RTMP por cima, produzindo
`rtmp://vps:1935/rtmp://mediamtx:1935/tenant-x/cam-y`, inválido para
qualquer client RTMP. Nenhum teste existia pra esse parsing até este bug
aparecer contra hardware real. Contraparte do servidor: `api/tests/
test_agent_config_router.py`.
"""
from __future__ import annotations

import httpx

from agent.cloud_client import CloudClient
from agent.config import Settings
from agent.stream_manager import StreamManager


def _settings() -> Settings:
    return Settings(
        agent_id="agent-1", agent_api_key="vms_chave", vms_api_url="http://vps.exemplo.com"
    )


class TestGetConfigParsesBarePath:
    async def test_mediamtx_path_field_is_read_verbatim(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "agent_id": "agent-1",
                "cameras": [{
                    "id": "cam-1", "name": "Câmera", "rtsp_url": "rtsp://cam/stream",
                    "is_active": True, "mediamtx_path": "tenant-x/cam-1",
                }],
            })

        client = CloudClient(_settings())
        client._client = httpx.AsyncClient(
            base_url="http://vps.exemplo.com", transport=httpx.MockTransport(handler)
        )

        config = await client.get_config()

        assert config.cameras[0].mediamtx_path == "tenant-x/cam-1"

    async def test_full_url_never_leaks_through_as_the_path(self) -> None:
        """Se o servidor um dia voltar a mandar uma URL completa por engano
        (regressão do lado dele), este teste não pega isso — é
        propositalmente escopado ao parsing deste lado. O que ele garante é
        que o client não faz nenhuma transformação própria que ADICIONE um
        esquema/host ao valor recebido."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "agent_id": "agent-1",
                "cameras": [{
                    "id": "cam-1", "name": "Câmera", "rtsp_url": "rtsp://cam/stream",
                    "is_active": True, "mediamtx_path": "tenant-x/cam-1",
                }],
            })

        client = CloudClient(_settings())
        client._client = httpx.AsyncClient(
            base_url="http://vps.exemplo.com", transport=httpx.MockTransport(handler)
        )

        config = await client.get_config()

        assert "://" not in config.cameras[0].mediamtx_path


class TestBuildRtmpUrlEndToEnd:
    """`StreamManager._build_rtmp_url` combinado com o path vindo do
    servidor — a regressão exata observada em produção: dois esquemas
    concatenados numa única string."""

    def test_produces_a_single_well_formed_rtmp_url(self) -> None:
        manager = StreamManager(mediamtx_rtmp_base="rtmp://vm-server.duckdns.org:1935")

        url = manager._build_rtmp_url("tenant-x/cam-1")

        assert url == "rtmp://vm-server.duckdns.org:1935/tenant-x/cam-1"
        # A regressão exata vista em produção: um segundo "rtmp://" ou
        # "mediamtx:1935" embutido no meio do caminho.
        assert url.count("rtmp://") == 1
        assert "mediamtx:1935" not in url

    def test_path_containing_a_scheme_would_be_caught_here(self) -> None:
        """Documenta o sintoma do bug antigo: se `mediamtx_path` viesse com
        uma URL completa (como antes do fix do servidor), o resultado
        ficaria visivelmente malformado — é isso que o teste do servidor
        (`test_agent_config_router.py`) impede de acontecer na origem."""
        manager = StreamManager(mediamtx_rtmp_base="rtmp://vm-server.duckdns.org:1935")

        malformed_path = "rtmp://mediamtx:1935/tenant-x/cam-1"  # o que vinha do bug
        url = manager._build_rtmp_url(malformed_path)

        assert url.count("rtmp://") == 2  # sintoma inequívoco do bug, se reaparecer
