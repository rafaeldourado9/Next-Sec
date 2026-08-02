"""Testes HTTP de `POST /edge/events:batch` (ADR-018 §5).

O que estes testes protegem: (1) idempotência — sem ela, todo timeout de rede
obriga o edge a escolher entre perder ou duplicar o evento; (2) isolamento de
tenant no lote — uma câmera de outro cliente não pode entrar por engano num
lote; (3) o comportamento sob cota estourada, que precisa ser "recusa limpa,
nada gravado", senão o agente não tem como saber o que reenviar.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.billing.models import LicenseKeyModel
from vms.cameras.models import AgentModel, CameraModel
from vms.edge import router as edge_router_module
from vms.edge.quota import QuotaDecision
from vms.edge.router import router as edge_router
from vms.events.models import VmsEventModel
from vms.iam.domain import ApiKeyOwnerType
from vms.iam.models import TenantModel
from vms.iam.repository import ApiKeyRepository
from vms.iam.service import ApiKeyService
from vms.infrastructure.exceptions import register_exception_handlers
from vms.shared.api.dependencies import get_db


@pytest_asyncio.fixture
async def agent_key(db_session: AsyncSession, tenant_a: TenantModel) -> str:
    """API key de agente do tenant A — a credencial que a ativação emite."""
    agent = AgentModel(id=str(uuid.uuid4()), tenant_id=tenant_a.id, name="edge-teste")
    db_session.add(agent)
    await db_session.flush()

    _, plain = await ApiKeyService(ApiKeyRepository(db_session)).issue_api_key(
        tenant_id=tenant_a.id, owner_type=ApiKeyOwnerType.AGENT, owner_id=agent.id
    )
    await db_session.flush()
    return plain


@pytest_asyncio.fixture
async def license_a(db_session: AsyncSession, tenant_a: TenantModel) -> LicenseKeyModel:
    license_key = LicenseKeyModel(
        id=str(uuid.uuid4()),
        license_key="ABCD-12345-67890-ABCDE-FGHIJ",
        tenant_id=tenant_a.id,
        status="active",
    )
    db_session.add(license_key)
    await db_session.flush()
    return license_key


@pytest_asyncio.fixture
async def camera_b(db_session: AsyncSession, tenant_b: TenantModel) -> CameraModel:
    """Câmera de OUTRO tenant — usada no teste de isolamento."""
    camera = CameraModel(id=str(uuid.uuid4()), tenant_id=tenant_b.id, name="Câmera do vizinho")
    db_session.add(camera)
    await db_session.flush()
    return camera


@pytest_asyncio.fixture
async def app(db_session: AsyncSession) -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(edge_router, prefix="/api/v1")
    register_exception_handlers(fastapi_app)

    # Sem Redis neste ambiente: `IngestQuota.check` falha aberta (ver docstring
    # dela) e o lote passa. Os testes de cota abaixo substituem a decisão
    # explicitamente em vez de depender desse fallback.
    fastapi_app.state.redis = None
    fastapi_app.state.arq_redis = None

    async def _override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    return fastapi_app


@pytest_asyncio.fixture
async def client(app: FastAPI):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _event(camera_id: str, **overrides: object) -> dict:
    base = {
        "client_event_id": str(uuid.uuid4()),
        "camera_id": camera_id,
        "event_type": "intrusion.detected",
        "occurred_at": datetime.now(UTC).isoformat(),
        "confidence": 0.91,
        "payload": {"class": "person"},
    }
    base.update(overrides)
    return base


async def _count_events(db: AsyncSession) -> int:
    return await db.scalar(select(func.count(VmsEventModel.id))) or 0


class TestBatchHappyPath:
    async def test_accepts_a_batch_and_persists_every_event(
        self, client: AsyncClient, db_session: AsyncSession,
        agent_key: str, camera_a: CameraModel,
    ) -> None:
        events = [_event(camera_a.id) for _ in range(5)]
        resp = await client.post(
            "/api/v1/edge/events:batch",
            headers={"Authorization": f"ApiKey {agent_key}"},
            json={"events": events},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["accepted"] == 5
        assert body["duplicates"] == 0
        assert body["rejected"] == 0
        assert len(body["results"]) == 5
        assert all(r["event_id"] for r in body["results"])
        assert await _count_events(db_session) == 5

    async def test_result_order_lets_the_agent_match_each_item(
        self, client: AsyncClient, agent_key: str, camera_a: CameraModel
    ) -> None:
        """O agente casa resultado com fila local pelo `client_event_id`, então
        todo item enviado precisa voltar — inclusive os recusados."""
        events = [_event(camera_a.id) for _ in range(3)]
        resp = await client.post(
            "/api/v1/edge/events:batch",
            headers={"Authorization": f"ApiKey {agent_key}"},
            json={"events": events},
        )

        returned = {r["client_event_id"] for r in resp.json()["results"]}
        assert returned == {e["client_event_id"] for e in events}

    async def test_rejects_batch_larger_than_the_declared_limit(
        self, client: AsyncClient, agent_key: str, camera_a: CameraModel
    ) -> None:
        resp = await client.post(
            "/api/v1/edge/events:batch",
            headers={"Authorization": f"ApiKey {agent_key}"},
            json={"events": [_event(camera_a.id) for _ in range(101)]},
        )
        assert resp.status_code == 422


class TestBatchIdempotency:
    async def test_resending_the_same_batch_does_not_duplicate(
        self, client: AsyncClient, db_session: AsyncSession,
        agent_key: str, camera_a: CameraModel,
    ) -> None:
        """Caso motivador: a VPS gravou, a resposta se perdeu, o agente reenvia."""
        events = [_event(camera_a.id) for _ in range(3)]
        headers = {"Authorization": f"ApiKey {agent_key}"}

        first = await client.post(
            "/api/v1/edge/events:batch", headers=headers, json={"events": events}
        )
        second = await client.post(
            "/api/v1/edge/events:batch", headers=headers, json={"events": events}
        )

        assert first.json()["accepted"] == 3
        assert second.json()["accepted"] == 0
        assert second.json()["duplicates"] == 3
        assert await _count_events(db_session) == 3

    async def test_duplicate_result_carries_the_original_event_id(
        self, client: AsyncClient, agent_key: str, camera_a: CameraModel
    ) -> None:
        """O agente precisa do ID real pra anexar foto/clipe do evento que já
        subiu — sem ele, a mídia de um reenvio ficaria órfã."""
        events = [_event(camera_a.id)]
        headers = {"Authorization": f"ApiKey {agent_key}"}

        first = await client.post(
            "/api/v1/edge/events:batch", headers=headers, json={"events": events}
        )
        second = await client.post(
            "/api/v1/edge/events:batch", headers=headers, json={"events": events}
        )

        assert second.json()["results"][0]["event_id"] == first.json()["results"][0]["event_id"]

    async def test_duplicate_inside_the_same_batch_does_not_break_it(
        self, client: AsyncClient, db_session: AsyncSession,
        agent_key: str, camera_a: CameraModel,
    ) -> None:
        """Um retry que se cruza com o envio original dentro do próprio outbox
        gera isso. Sem tratar em memória, o INSERT violaria o índice único e
        derrubaria o lote inteiro — perdendo eventos válidos junto."""
        repeated = _event(camera_a.id)
        resp = await client.post(
            "/api/v1/edge/events:batch",
            headers={"Authorization": f"ApiKey {agent_key}"},
            json={"events": [repeated, _event(camera_a.id), dict(repeated)]},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["accepted"] == 2
        assert resp.json()["duplicates"] == 1
        assert await _count_events(db_session) == 2


class TestBatchTenantIsolation:
    async def test_camera_from_another_tenant_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession,
        agent_key: str, camera_a: CameraModel, camera_b: CameraModel,
    ) -> None:
        resp = await client.post(
            "/api/v1/edge/events:batch",
            headers={"Authorization": f"ApiKey {agent_key}"},
            json={"events": [_event(camera_a.id), _event(camera_b.id)]},
        )

        body = resp.json()
        assert body["accepted"] == 1
        assert body["rejected"] == 1
        # Recusa o item, não o lote: o evento legítimo do mesmo lote não pode
        # ser penalizado por um vizinho inválido.
        assert await _count_events(db_session) == 1

    async def test_unknown_camera_is_rejected_not_silently_dropped(
        self, client: AsyncClient, agent_key: str, camera_a: CameraModel
    ) -> None:
        resp = await client.post(
            "/api/v1/edge/events:batch",
            headers={"Authorization": f"ApiKey {agent_key}"},
            json={"events": [_event(str(uuid.uuid4()))]},
        )

        result = resp.json()["results"][0]
        assert result["status"] == "rejected"
        assert result["reason"]

    async def test_revoked_api_key_is_refused(
        self, client: AsyncClient, camera_a: CameraModel
    ) -> None:
        resp = await client.post(
            "/api/v1/edge/events:batch",
            headers={"Authorization": "ApiKey vms_chave_que_nao_existe"},
            json={"events": [_event(camera_a.id)]},
        )
        assert resp.status_code == 401


class TestBatchQuota:
    async def test_over_quota_returns_429_with_retry_after(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
        agent_key: str, camera_a: CameraModel, license_a: LicenseKeyModel,
    ) -> None:
        async def _denied(self, tenant_id, events_per_minute, cost):  # noqa: ANN001
            return QuotaDecision(allowed=False, remaining=0, retry_after_seconds=17)

        monkeypatch.setattr(edge_router_module.IngestQuota, "check", _denied)

        resp = await client.post(
            "/api/v1/edge/events:batch",
            headers={"Authorization": f"ApiKey {agent_key}"},
            json={"events": [_event(camera_a.id)]},
        )

        assert resp.status_code == 429
        assert resp.headers["Retry-After"] == "17"
        assert resp.headers["X-RateLimit-Remaining"] == "0"

    async def test_over_quota_writes_nothing(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
        agent_key: str, camera_a: CameraModel, license_a: LicenseKeyModel,
    ) -> None:
        """O lote inteiro tem que voltar pro outbox intacto — aceitar parte dele
        sem informar quais deixaria o agente sem saber o que reenviar."""
        async def _denied(self, tenant_id, events_per_minute, cost):  # noqa: ANN001
            return QuotaDecision(allowed=False, remaining=0, retry_after_seconds=5)

        monkeypatch.setattr(edge_router_module.IngestQuota, "check", _denied)

        await client.post(
            "/api/v1/edge/events:batch",
            headers={"Authorization": f"ApiKey {agent_key}"},
            json={"events": [_event(camera_a.id) for _ in range(4)]},
        )
        assert await _count_events(db_session) == 0

    async def test_quota_cost_is_the_batch_size_not_one(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
        agent_key: str, camera_a: CameraModel, license_a: LicenseKeyModel,
    ) -> None:
        """Cobrar 1 por request faria um lote de 100 custar o mesmo que um de 1
        — e a cota deixaria de significar 'eventos por minuto'."""
        seen: dict[str, int] = {}

        async def _record(self, tenant_id, events_per_minute, cost):  # noqa: ANN001
            seen["cost"] = cost
            seen["limit"] = events_per_minute
            return QuotaDecision(allowed=True, remaining=99, retry_after_seconds=0)

        monkeypatch.setattr(edge_router_module.IngestQuota, "check", _record)

        await client.post(
            "/api/v1/edge/events:batch",
            headers={"Authorization": f"ApiKey {agent_key}"},
            json={"events": [_event(camera_a.id) for _ in range(7)]},
        )
        assert seen["cost"] == 7
        assert seen["limit"] == 120


class TestHeartbeat:
    async def test_heartbeat_returns_current_policy(
        self, client: AsyncClient, db_session: AsyncSession,
        agent_key: str, license_a: LicenseKeyModel,
    ) -> None:
        """Mudar a cota pelo painel precisa chegar na instalação sem ninguém
        tocar na máquina do cliente."""
        license_a.events_per_minute = 300
        license_a.clip_seconds = 20
        await db_session.flush()

        resp = await client.post(
            "/api/v1/edge/heartbeat",
            headers={"Authorization": f"ApiKey {agent_key}"},
            json={"agent_version": "1.2.0", "outbox_pending": 42},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["policy"]["events_per_minute"] == 300
        assert resp.json()["policy"]["clip_seconds"] == 20
        assert resp.json()["license_status"] == "active"

    async def test_heartbeat_records_last_seen(
        self, client: AsyncClient, db_session: AsyncSession,
        agent_key: str, license_a: LicenseKeyModel,
    ) -> None:
        await client.post(
            "/api/v1/edge/heartbeat",
            headers={"Authorization": f"ApiKey {agent_key}"},
            json={"agent_version": "1.2.0"},
        )

        await db_session.refresh(license_a)
        assert license_a.last_seen_at is not None
        assert license_a.agent_version == "1.2.0"
