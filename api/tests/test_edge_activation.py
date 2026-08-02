"""Testes HTTP de `POST /edge/activate` e do desvínculo por admin (ADR-018 §1).

Mesmo padrão de isolamento das demais suítes: sobe só o router num FastAPI
mínimo sobre o SQLite em memória do `conftest.py`, sem Postgres/Redis reais.

O que estes testes protegem, em ordem de importância: (1) a licença só vale
numa máquina — é o que impede uma licença vendida de virar N instalações;
(2) reinstalar na MESMA máquina precisa funcionar sem suporte, senão o
mecanismo vira um gerador de chamados; (3) a API key antiga morre em toda
reemissão, senão o vínculo não significa nada na prática.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.admin.router import router as admin_router
from vms.billing.models import LicenseKeyModel
from vms.cameras.models import AgentModel
from vms.edge.router import router as edge_router
from vms.iam.models import ApiKeyModel, TenantModel
from vms.infrastructure.exceptions import register_exception_handlers
from vms.shared.api.dependencies import TokenClaims, get_current_user, get_db

_FINGERPRINT_A = "a" * 64
_FINGERPRINT_B = "b" * 64


@pytest_asyncio.fixture
async def app(db_session: AsyncSession) -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(edge_router, prefix="/api/v1")
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
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def license_a(db_session: AsyncSession, tenant_a: TenantModel) -> LicenseKeyModel:
    """Licença ativa e vinculada ao tenant, ainda não usada por nenhuma máquina."""
    license_key = LicenseKeyModel(
        id=str(uuid.uuid4()),
        license_key="ABCD-12345-67890-ABCDE-FGHIJ",
        tenant_id=tenant_a.id,
        status="active",
        max_cameras=8,
    )
    db_session.add(license_key)
    await db_session.flush()
    return license_key


def _body(**overrides: object) -> dict:
    base = {
        "license_key": "ABCD-12345-67890-ABCDE-FGHIJ",
        "hardware_fingerprint": _FINGERPRINT_A,
        "hostname": "PDV-LOJA-03",
        "agent_version": "1.0.0",
    }
    base.update(overrides)
    return base


class TestActivateHappyPath:
    async def test_returns_credentials_and_policy(
        self, client: AsyncClient, license_a: LicenseKeyModel, tenant_a: TenantModel
    ) -> None:
        resp = await client.post("/api/v1/edge/activate", json=_body())

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["tenant_id"] == tenant_a.id
        assert body["tenant_name"] == tenant_a.name
        assert body["api_key"]
        assert body["agent_id"]
        # Sem `rtmp_url`, um agente na casa do cliente publicaria em
        # `rtmp://mediamtx:1935` — nome que só resolve dentro da rede Docker
        # da VPS. O vídeo simplesmente não chegaria.
        assert body["rtmp_url"].startswith("rtmp://")
        # A policy é o que faz o agente se autolimitar sem nada hardcoded nele.
        assert body["policy"]["events_per_minute"] == 120
        assert body["policy"]["clip_seconds"] == 15
        assert body["policy"]["clip_max_height"] == 480

    async def test_binds_license_to_the_machine(
        self, client: AsyncClient, db_session: AsyncSession, license_a: LicenseKeyModel
    ) -> None:
        resp = await client.post("/api/v1/edge/activate", json=_body())
        assert resp.status_code == 200

        await db_session.refresh(license_a)
        assert license_a.hardware_fingerprint == _FINGERPRINT_A
        assert license_a.activated_hostname == "PDV-LOJA-03"
        assert license_a.agent_version == "1.0.0"
        assert license_a.activated_at is not None
        assert license_a.agent_id == resp.json()["agent_id"]

    async def test_creates_agent_and_completes_onboarding(
        self, client: AsyncClient, db_session: AsyncSession,
        license_a: LicenseKeyModel, tenant_a: TenantModel,
    ) -> None:
        resp = await client.post("/api/v1/edge/activate", json=_body())
        assert resp.status_code == 200

        agent = await db_session.get(AgentModel, resp.json()["agent_id"])
        assert agent is not None
        assert agent.tenant_id == tenant_a.id
        # Nome do agent = hostname da máquina: é assim que o suporte identifica
        # qual instalação é qual sem pedir nada ao cliente.
        assert agent.name == "PDV-LOJA-03"

        await db_session.refresh(tenant_a)
        assert tenant_a.onboarding_complete is True

    async def test_accepts_key_as_typed_by_the_customer(
        self, client: AsyncClient, license_a: LicenseKeyModel
    ) -> None:
        """Minúscula e com espaços colados — como sai de um copiar/colar real."""
        resp = await client.post(
            "/api/v1/edge/activate",
            json=_body(license_key="  abcd-12345-67890-abcde-fghij "),
        )
        assert resp.status_code == 200

    async def test_rejects_malformed_key_before_touching_the_database(
        self, client: AsyncClient, license_a: LicenseKeyModel
    ) -> None:
        resp = await client.post("/api/v1/edge/activate", json=_body(license_key="123"))
        assert resp.status_code == 422


class TestActivateSameMachine:
    """Reinstalar na mesma máquina não pode exigir suporte."""

    async def test_reactivation_is_idempotent_and_keeps_the_agent(
        self, client: AsyncClient, license_a: LicenseKeyModel
    ) -> None:
        first = await client.post("/api/v1/edge/activate", json=_body())
        second = await client.post("/api/v1/edge/activate", json=_body())

        assert second.status_code == 200
        # Mesmo agent: as câmeras do cliente estão ligadas a esse ID — criar um
        # novo a cada reinstalação órfãnaria toda a configuração dele.
        assert second.json()["agent_id"] == first.json()["agent_id"]
        assert second.json()["api_key"] != first.json()["api_key"]

    async def test_previous_api_key_is_revoked(
        self, client: AsyncClient, db_session: AsyncSession, license_a: LicenseKeyModel
    ) -> None:
        first = await client.post("/api/v1/edge/activate", json=_body())
        await client.post("/api/v1/edge/activate", json=_body())

        agent_id = first.json()["agent_id"]
        keys = (await db_session.execute(
            select(ApiKeyModel).where(ApiKeyModel.owner_id == agent_id)
        )).scalars().all()

        # Duas chaves emitidas, exatamente uma ativa — a nova. Sem isso, cada
        # reinstalação deixaria mais uma credencial válida solta por aí.
        assert len(keys) == 2
        assert sum(1 for k in keys if k.is_active) == 1


class TestActivateOtherMachine:
    async def test_second_machine_is_refused_with_conflict(
        self, client: AsyncClient, license_a: LicenseKeyModel
    ) -> None:
        await client.post("/api/v1/edge/activate", json=_body())
        resp = await client.post(
            "/api/v1/edge/activate", json=_body(hardware_fingerprint=_FINGERPRINT_B)
        )

        assert resp.status_code == 409
        assert "outra máquina" in resp.json()["message"]

    async def test_second_machine_gets_no_credentials(
        self, client: AsyncClient, db_session: AsyncSession, license_a: LicenseKeyModel
    ) -> None:
        await client.post("/api/v1/edge/activate", json=_body())
        resp = await client.post(
            "/api/v1/edge/activate", json=_body(hardware_fingerprint=_FINGERPRINT_B)
        )

        assert "api_key" not in resp.json()
        agents = (await db_session.execute(select(AgentModel))).scalars().all()
        assert len(agents) == 1


class TestActivateRefusals:
    @pytest.mark.parametrize(
        ("field", "value", "expected_status"),
        [
            ("status", "suspended", 400),
            ("status", "revoked", 400),
            ("tenant_id", None, 400),
        ],
    )
    async def test_unusable_license(
        self, client: AsyncClient, db_session: AsyncSession, license_a: LicenseKeyModel,
        field: str, value: object, expected_status: int,
    ) -> None:
        setattr(license_a, field, value)
        await db_session.flush()

        resp = await client.post("/api/v1/edge/activate", json=_body())
        assert resp.status_code == expected_status

    async def test_expired_license(
        self, client: AsyncClient, db_session: AsyncSession, license_a: LicenseKeyModel
    ) -> None:
        license_a.expires_at = datetime.now(UTC) - timedelta(days=1)
        await db_session.flush()

        resp = await client.post("/api/v1/edge/activate", json=_body())
        assert resp.status_code == 400
        assert "expirada" in resp.json()["message"].lower()

    async def test_unknown_license(self, client: AsyncClient, license_a: LicenseKeyModel) -> None:
        resp = await client.post(
            "/api/v1/edge/activate", json=_body(license_key="ZZZZ-99999-99999-99999-99999")
        )
        assert resp.status_code == 404

    async def test_suspended_tenant(
        self, client: AsyncClient, db_session: AsyncSession,
        license_a: LicenseKeyModel, tenant_a: TenantModel,
    ) -> None:
        tenant_a.is_active = False
        await db_session.flush()

        resp = await client.post("/api/v1/edge/activate", json=_body())
        assert resp.status_code == 400
        assert "suspensa" in resp.json()["message"].lower()


class TestUnbind:
    async def test_unbind_frees_the_license_for_a_new_machine(
        self, client: AsyncClient, license_a: LicenseKeyModel
    ) -> None:
        await client.post("/api/v1/edge/activate", json=_body())

        unbind = await client.post(f"/api/v1/admin/licenses/{license_a.id}/unbind")
        assert unbind.status_code == 200

        resp = await client.post(
            "/api/v1/edge/activate", json=_body(hardware_fingerprint=_FINGERPRINT_B)
        )
        assert resp.status_code == 200

    async def test_unbind_revokes_the_old_installation_credentials(
        self, client: AsyncClient, db_session: AsyncSession, license_a: LicenseKeyModel
    ) -> None:
        """Desvincular sem revogar deixaria a máquina antiga enviando eventos
        indefinidamente — o vínculo só significa algo se a credencial morre junto."""
        first = await client.post("/api/v1/edge/activate", json=_body())
        agent_id = first.json()["agent_id"]

        await client.post(f"/api/v1/admin/licenses/{license_a.id}/unbind")

        keys = (await db_session.execute(
            select(ApiKeyModel).where(ApiKeyModel.owner_id == agent_id)
        )).scalars().all()
        assert keys
        assert all(not k.is_active for k in keys)

    async def test_unbind_unknown_license_is_404(self, client: AsyncClient) -> None:
        resp = await client.post(f"/api/v1/admin/licenses/{uuid.uuid4()}/unbind")
        assert resp.status_code == 404
