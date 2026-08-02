"""`GET /agents/me/config` — path do MediaMTX, não URL RTMP completa.

Bug real de produção (2026-08-02, primeiro teste ponta a ponta de um agent
nativo Windows publicando de verdade): este endpoint mandava `rtmp_push_url`
já como URL RTMP **completa**, montada com o host INTERNO da VPS
(`rtmp://mediamtx:1935/...`, que só resolve dentro da rede Docker) — e o
agent, que tratava esse campo como se fosse só um path, prefixava a própria
base RTMP por cima. Resultado em produção:
`rtmp://vm-server.duckdns.org:1935/rtmp://mediamtx:1935/tenant-x/cam-y`,
inválido para qualquer client RTMP. Nenhum teste existia pra esse endpoint
até este bug ser descoberto testando com hardware real.

Sem cobertura equivalente no lado do agent aqui — ver
`edge_agent/tests/test_cloud_client_config.py`.
"""
from __future__ import annotations

import uuid

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from vms.cameras.models import AgentModel, CameraModel
from vms.cameras.router import router as cameras_router
from vms.iam.domain import ApiKeyOwnerType
from vms.iam.models import TenantModel
from vms.iam.repository import ApiKeyRepository
from vms.iam.service import ApiKeyService
from vms.infrastructure.exceptions import register_exception_handlers
from vms.shared.api.dependencies import get_db


@pytest_asyncio.fixture
async def agent_a(db_session: AsyncSession, tenant_a: TenantModel) -> AgentModel:
    agent = AgentModel(id=str(uuid.uuid4()), tenant_id=tenant_a.id, name="agent-config-teste")
    db_session.add(agent)
    await db_session.flush()
    return agent


@pytest_asyncio.fixture
async def agent_api_key(db_session: AsyncSession, tenant_a: TenantModel, agent_a: AgentModel) -> str:
    _, plain = await ApiKeyService(ApiKeyRepository(db_session)).issue_api_key(
        tenant_id=tenant_a.id, owner_type=ApiKeyOwnerType.AGENT, owner_id=agent_a.id
    )
    await db_session.flush()
    return plain


@pytest_asyncio.fixture
async def camera_of_agent(
    db_session: AsyncSession, tenant_a: TenantModel, agent_a: AgentModel
) -> CameraModel:
    camera = CameraModel(
        id=str(uuid.uuid4()),
        tenant_id=tenant_a.id,
        name="Câmera do agent",
        agent_id=agent_a.id,
        stream_protocol="rtsp_pull",
        rtsp_url="rtsp://admin:pass@192.168.0.101:554/Streaming/Channels/101",
        is_active=True,
    )
    db_session.add(camera)
    await db_session.flush()
    return camera


@pytest_asyncio.fixture
async def app(db_session: AsyncSession) -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(cameras_router, prefix="/api/v1")
    register_exception_handlers(fastapi_app)

    async def _override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    return fastapi_app


@pytest_asyncio.fixture
async def client(app: FastAPI):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAgentConfigMediamtxPath:
    async def test_mediamtx_path_is_a_bare_path_not_a_url(
        self, client: AsyncClient, agent_api_key: str, camera_of_agent: CameraModel,
        tenant_a: TenantModel,
    ) -> None:
        """A regressão exata do bug: o campo não pode conter nenhum esquema
        de URL nem host — o agent é quem sabe (e monta) sua própria base
        RTMP; o servidor nunca deveria embutir isso."""
        resp = await client.get(
            "/api/v1/agents/me/config", headers={"Authorization": f"ApiKey {agent_api_key}"}
        )

        assert resp.status_code == 200, resp.text
        cameras = resp.json()["cameras"]
        assert len(cameras) == 1

        path = cameras[0]["mediamtx_path"]
        assert path == f"tenant-{tenant_a.id}/cam-{camera_of_agent.id}"
        assert "://" not in path
        assert "rtmp" not in path.lower()
        assert "mediamtx:" not in path

    async def test_response_has_no_legacy_rtmp_push_url_field(
        self, client: AsyncClient, agent_api_key: str, camera_of_agent: CameraModel
    ) -> None:
        """Trava o rename: se `rtmp_push_url` reaparecer (ex.: alguém
        reverte a mudança pela metade), o contrato volta a ambiguar path
        com URL completa."""
        resp = await client.get(
            "/api/v1/agents/me/config", headers={"Authorization": f"ApiKey {agent_api_key}"}
        )
        assert "rtmp_push_url" not in resp.json()["cameras"][0]
