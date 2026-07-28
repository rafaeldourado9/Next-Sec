"""Testes HTTP de `POST /admin/onboard-client` (Sprint 7 — onboarding por
licença + instalador único Nível 1). Sobe só o router de admin num FastAPI
mínimo (mesmo padrão de test_plugins_events_router.py) com a sessão de banco
sobrescrita pro SQLite em memória e `get_current_user` sobrescrito pra
simular um admin autenticado — não há túnel WireGuard real disponível neste
ambiente de teste, então `WireGuardHubClient` é substituído por um fake
(`_FakeWireGuardHubClient`/`_FailingWireGuardHubClient`) via monkeypatch.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import vms.admin.router as admin_router_module
from vms.admin.router import router as admin_router
from vms.audit.models import AuditLogModel
from vms.billing.models import LicenseKeyModel
from vms.cameras.models import AgentModel, AgentTunnelModel
from vms.cameras.repository import AgentTunnelRepository
from vms.iam.models import ApiKeyModel, TenantModel, UserModel
from vms.infrastructure.exceptions import register_exception_handlers
from vms.infrastructure.security import verify_password
from vms.shared.api.dependencies import get_current_user, get_db, TokenClaims


class _FakeWireGuardHubClient:
    """Substitui o cliente real do hub WG — nenhum hub roda no ambiente de teste."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def get_hub_info(self) -> dict[str, str]:
        return {"public_key": "hub-fake-pubkey", "endpoint": "vpn.example.com:51820"}

    async def add_peer(self, public_key: str, tunnel_ip: str) -> None:
        return None

    async def remove_peer(self, public_key: str) -> None:
        return None


class _FailingWireGuardHubClient(_FakeWireGuardHubClient):
    """Simula o hub inacessível — usado no teste de rollback."""

    async def get_hub_info(self) -> dict[str, str]:
        raise ConnectionError("hub WireGuard inacessível (simulado)")


@pytest_asyncio.fixture
async def app(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    # SQLite (fixture de teste) não tem sequences do Postgres — a alocação
    # real de IP do túnel (`agent_tunnel_ip_seq`) só existe lá. Sem hub WG de
    # verdade neste ambiente de qualquer forma, um contador incremental
    # simples já cobre o que o teste precisa verificar.
    _counter = {"n": 0}

    async def _fake_next_ip_offset(self: AgentTunnelRepository) -> int:
        _counter["n"] += 1
        return _counter["n"]

    monkeypatch.setattr(AgentTunnelRepository, "next_ip_offset", _fake_next_ip_offset)

    fastapi_app = FastAPI()
    fastapi_app.include_router(admin_router, prefix="/api/v1")
    register_exception_handlers(fastapi_app)

    async def _override_get_db():
        yield db_session

    async def _override_current_user():
        return TokenClaims(user_id=str(uuid.uuid4()), tenant_id=str(uuid.uuid4()), role="admin")

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    fastapi_app.dependency_overrides[get_current_user] = _override_current_user
    return fastapi_app


@pytest_asyncio.fixture
async def client(app: FastAPI):
    # raise_app_exceptions=False — reproduz o comportamento real de produção
    # (exceção não tratada vira 500, ver handler genérico em vms/main.py) em
    # vez do padrão do httpx de propagar a exceção pro código do teste.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _body(**overrides: object) -> dict:
    base = {
        "name": "Cliente Piloto",
        "slug": f"cliente-piloto-{uuid.uuid4().hex[:6]}",
        "gestor_email": "gestor@clientepiloto.com.br",
        "gestor_name": "Fulano",
        "max_cameras": 8,
    }
    base.update(overrides)
    return base


class TestOnboardClientHappyPath:
    async def test_creates_tenant_user_license_and_agent(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(admin_router_module, "WireGuardHubClient", _FakeWireGuardHubClient)

        body = _body()
        resp = await client.post("/api/v1/admin/onboard-client", json=body)

        assert resp.status_code == 201, resp.text
        data = resp.json()

        assert data["tenant"]["slug"] == body["slug"]
        assert data["gestor_email"] == body["gestor_email"]
        assert len(data["gestor_default_password"]) >= 8
        assert data["license_key"].count("-") == 4
        assert data["agent"]["api_key"].startswith("vms_") or len(data["agent"]["api_key"]) > 10
        assert data["agent"]["wg_private_key"]
        assert data["agent"]["wg_public_key_hub"] == "hub-fake-pubkey"

        tenant = await db_session.scalar(select(TenantModel).where(TenantModel.slug == body["slug"]))
        assert tenant is not None
        assert tenant.onboarding_complete is True
        assert tenant.license_key_id is not None

        gestor = await db_session.scalar(
            select(UserModel).where(UserModel.email == body["gestor_email"], UserModel.tenant_id == tenant.id)
        )
        assert gestor is not None
        assert gestor.role == "gestor"
        assert gestor.must_change_password is True
        assert verify_password(data["gestor_default_password"], gestor.hashed_password)

        license_key = await db_session.get(LicenseKeyModel, tenant.license_key_id)
        assert license_key is not None
        assert license_key.status == "active"
        assert license_key.tenant_id == tenant.id
        assert license_key.activated_at is not None

        agent = await db_session.scalar(select(AgentModel).where(AgentModel.tenant_id == tenant.id))
        assert agent is not None
        assert agent.name == f"{body['slug']}-docker"

        tunnel = await db_session.scalar(select(AgentTunnelModel).where(AgentTunnelModel.agent_id == agent.id))
        assert tunnel is not None
        assert tunnel.public_key

        api_key_row = await db_session.scalar(
            select(ApiKeyModel).where(ApiKeyModel.owner_id == agent.id, ApiKeyModel.owner_type == "agent")
        )
        assert api_key_row is not None
        assert api_key_row.is_active is True

        audit = await db_session.scalar(
            select(AuditLogModel).where(AuditLogModel.action == "admin.client.onboarded")
        )
        assert audit is not None
        assert audit.resource_id == tenant.id

    async def test_duplicate_slug_returns_409(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(admin_router_module, "WireGuardHubClient", _FakeWireGuardHubClient)

        body = _body()
        first = await client.post("/api/v1/admin/onboard-client", json=body)
        assert first.status_code == 201

        second = await client.post("/api/v1/admin/onboard-client", json=_body(slug=body["slug"]))
        assert second.status_code == 409

    async def test_missing_required_fields_returns_400(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/admin/onboard-client", json={"name": "Só nome"})
        assert resp.status_code == 400


class TestOnboardClientWireGuardRollback:
    async def test_hub_failure_rolls_back_agent_but_keeps_tenant_and_license(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Achado esperado: `create_agent_with_tunnel` só desfaz o AGENT (e sua
        api key) se o hub falhar — não existe (nem deveria existir, seria
        sobre-engenharia pra este MVP) uma saga que também desfaça
        tenant/usuário/licença já commitados antes do agent. Documentamos o
        comportamento real: o admin precisa saber que um onboarding com falha
        de túnel deixa tenant/licença criados, só sem agent — e pode tentar
        provisionar o agent de novo depois (fora do escopo desta task)."""
        monkeypatch.setattr(admin_router_module, "WireGuardHubClient", _FailingWireGuardHubClient)

        body = _body()
        resp = await client.post("/api/v1/admin/onboard-client", json=body)

        assert resp.status_code >= 500

        tenant = await db_session.scalar(select(TenantModel).where(TenantModel.slug == body["slug"]))
        assert tenant is not None, "tenant já teria sido commitado antes da falha do hub"

        agent = await db_session.scalar(select(AgentModel).where(AgentModel.tenant_id == tenant.id))
        assert agent is None, "agent deveria ter sido desfeito pelo rollback de create_agent_with_tunnel"
