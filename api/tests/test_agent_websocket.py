"""WebSocket de config push do agent (`/agents/me/ws`) contra Redis real.

Cobre dois bugs de produção achados testando um agente de verdade (Windows,
serviço NSSM) contra a VPS real — nenhum dos dois tinha teste algum até aqui,
o que é exatamente por que sobreviveram desde o Sprint 7:

1. **Busy-loop de CPU**: `pubsub.get_message(...)` sem `timeout=` retorna
   quase instantâneo (default do redis-py é não-bloqueante) — o
   `asyncio.wait_for(..., timeout=30.0)` de fora nunca esperava de verdade, e
   o loop girava sem pausa, 100% de um core por agente conectado.
2. **Crash ao publicar qualquer mensagem**: o client Redis usado aqui não
   passa `decode_responses=True`, então `message["data"]` chega em `bytes` —
   e o handler tentava mandar isso como frame de texto do WebSocket.

**Por que um servidor uvicorn real, não `starlette.testclient.TestClient`**:
tentativa inicial. `TestClient` roda o app inteiro em memória, sem cruzar a
camada de protocolo WS de verdade — `WebSocket.send_text` só empacota
`{"text": data}` num dict e entrega pro transporte; é a implementação real do
protocolo (dentro de `uvicorn`/`websockets`, ao montar o frame de texto no
fio) que exige `str` e falha com `'bytes' object has no attribute 'encode'`
se receber bytes. Contra `TestClient`, o bug #2 (bytes) simplesmente não se
manifesta — o teste passaria mesmo com o código quebrado, um falso-negativo
silencioso. Verificado empiricamente nesta sessão: revertido o fix
temporariamente, a suíte com `TestClient` continuou verde. Por isso aqui sobe
um `uvicorn.Server` de verdade numa thread e conecta com a MESMA biblioteca
`websockets` que `edge_agent/src/agent/cloud_client.py` usa em produção —
mesma dupla de bugs, mesmo caminho de código, cliente real.

Gated por `EDGE_QUOTA_TEST_REDIS_URL` (mesma variável usada por
`test_edge_quota_redis.py`) — pub/sub real não roda contra SQLite nem mock, e
reaproveitar a env var evita inventar uma segunda só pra isso.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import pytest_asyncio
import uvicorn
import websockets
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vms.cameras.models import AgentModel
from vms.cameras.router import router as cameras_router
from vms.iam.domain import ApiKeyOwnerType
from vms.iam.models import TenantModel
from vms.iam.repository import ApiKeyRepository
from vms.iam.service import ApiKeyService
from vms.infrastructure.database.connection import Base, init_db

_REDIS_URL = os.getenv("EDGE_QUOTA_TEST_REDIS_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _REDIS_URL, reason="EDGE_QUOTA_TEST_REDIS_URL não definida"),
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _LiveServer:
    """Servidor uvicorn real, numa thread, dentro do processo de teste.

    `agent_ws` não usa `Depends(get_db)` de verdade (ver nota abaixo) — usa
    `get_session_factory()`, a factory global configurada uma única vez por
    `init_db()`. Sobe/desce no mesmo processo pytest, então basta chamar
    `init_db()` com uma engine SQLite isolada antes de iniciar o servidor.
    """

    def __init__(self, app: FastAPI, port: int) -> None:
        self._config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self._server = uvicorn.Server(self._config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + 10.0
        while not self._server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not self._server.started:
            raise RuntimeError("Servidor uvicorn de teste não subiu a tempo")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10.0)


@pytest_asyncio.fixture
async def wired_db(tmp_path: Path):
    """Aponta a factory GLOBAL (`get_session_factory`) pra um SQLite em
    arquivo próprio deste teste, e desfaz no fim.

    Nota não-óbvia: `agent_ws` declara `db: DbSession = None` na assinatura
    mas NUNCA usa esse parâmetro — chama `get_session_factory()` direto (a
    mesma factory que `main.py::lifespan` configura em produção via
    `init_db(engine)`). `app.dependency_overrides[get_db]` não teria efeito
    nenhum aqui; é por isso que a montagem do banco de teste passa por
    `init_db()`, não pelo mecanismo usual de override do FastAPI.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ws-test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    init_db(engine)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def agent_key(wired_db) -> tuple[str, str]:
    """`(agent_id, api_key_plain)` — mesma credencial que um agente real usa."""
    factory = async_sessionmaker(wired_db, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        tenant = TenantModel(id=str(uuid.uuid4()), name="Tenant WS", slug=f"ws-{uuid.uuid4().hex[:6]}")
        session.add(tenant)
        await session.flush()

        agent = AgentModel(id=str(uuid.uuid4()), tenant_id=tenant.id, name="ws-teste")
        session.add(agent)
        await session.flush()

        _, plain = await ApiKeyService(ApiKeyRepository(session)).issue_api_key(
            tenant_id=tenant.id, owner_type=ApiKeyOwnerType.AGENT, owner_id=agent.id
        )
        await session.commit()
        return agent.id, plain


@pytest.fixture
def live_server(wired_db) -> Iterator[str]:  # type: ignore[valid-type]
    """Sobe o app real (mesmo router de produção) num uvicorn de verdade.
    Devolve a URL base ws://."""
    app = FastAPI()
    app.include_router(cameras_router, prefix="/api/v1")

    port = _free_port()
    server = _LiveServer(app, port)
    server.start()
    try:
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.stop()


async def _publish(agent_id: str, payload: dict) -> None:
    """Publica no MESMO canal que `agent_ws` assina — simula o que
    `_send_agent_command`/config push fazem em produção."""
    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(_REDIS_URL)
    try:
        await redis_client.publish(f"agent:{agent_id}:config", json.dumps(payload))
    finally:
        await redis_client.aclose()


async def _publish_until_received(
    base_url: str, api_key: str, agent_id: str, payload: dict, *, overall_timeout: float = 8.0
) -> str:
    """Conecta com o cliente `websockets` real (mesma lib que
    `edge_agent/src/agent/cloud_client.py` usa) e republica até a mensagem
    chegar.

    Corrida real, não bug de produção: a conexão TCP/handshake completa
    antes de o handler terminar `pubsub.subscribe()` no servidor — publicar
    uma única vez logo em seguida arriscaria perder a mensagem (pub/sub não
    tem replay). `_send_agent_command` nunca corre esse risco porque o agent
    já está conectado há muito tempo quando um comando é de fato disparado.
    """
    url = f"{base_url}/api/v1/agents/me/ws?api_key={api_key}"
    async with websockets.connect(url) as ws:
        deadline = time.monotonic() + overall_timeout
        while time.monotonic() < deadline:
            await _publish(agent_id, payload)
            try:
                return await asyncio.wait_for(ws.recv(), timeout=0.3)
            except TimeoutError:
                continue
        raise AssertionError("Mensagem não chegou dentro do timeout")


class TestConfigPushDelivery:
    async def test_published_message_is_forwarded_as_text(
        self, live_server: str, agent_key: tuple[str, str]
    ) -> None:
        """Sem o decode de bytes→str, o servidor derrubava a conexão ao
        tentar montar o frame de texto — o client via a conexão fechar sem
        nunca receber nada."""
        agent_id, api_key = agent_key
        received = await _publish_until_received(
            live_server, api_key, agent_id, {"event": "config_updated"}
        )
        assert json.loads(received) == {"event": "config_updated"}

    async def test_connection_survives_multiple_messages(
        self, live_server: str, agent_key: tuple[str, str]
    ) -> None:
        """Regressão direta do bug de crash: antes do fix, a PRIMEIRA
        mensagem publicada já derrubava a conexão — uma segunda nunca
        chegaria porque não haveria mais handler do lado de lá."""
        agent_id, api_key = agent_key
        url = f"{live_server}/api/v1/agents/me/ws?api_key={api_key}"

        async with websockets.connect(url) as ws:
            deadline = time.monotonic() + 8.0
            first: str | None = None
            while time.monotonic() < deadline and first is None:
                await _publish(agent_id, {"event": "camera_added"})
                try:
                    first = await asyncio.wait_for(ws.recv(), timeout=0.3)
                except TimeoutError:
                    continue

            assert first is not None, "primeira mensagem não chegou"

            # Já dentro da conexão estabelecida — sem corrida de subscribe
            # pendente, uma publicação simples basta pra segunda mensagem.
            await _publish(agent_id, {"event": "camera_removed"})
            second = await asyncio.wait_for(ws.recv(), timeout=5.0)

        assert json.loads(first) == {"event": "camera_added"}
        assert json.loads(second) == {"event": "camera_removed"}

    async def test_invalid_api_key_is_refused(self, live_server: str, wired_db) -> None:
        url = f"{live_server}/api/v1/agents/me/ws?api_key=vms_inexistente"
        with pytest.raises(websockets.exceptions.ConnectionClosed):
            async with websockets.connect(url) as ws:
                await ws.recv()
