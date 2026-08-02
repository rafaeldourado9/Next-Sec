"""Upload de foto e clipe dos eventos aceitos no lote (ADR-018 §4/§5).

Segundo passo do fluxo de ingestão: o `:batch` sobe só metadado, e a mídia vem
depois, só para os eventos que a VPS aceitou. O que estes testes protegem:
(1) isolamento de tenant nos dois endpoints — o `event_id` é um UUID que viaja
no path e cada cliente tem sua própria key; (2) a cota de storage recusando o
clipe **sem** derrubar evento e foto, que é o comportamento deliberado.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import vms.event_clips.service as clip_service_module
from vms.billing.models import LicenseKeyModel
from vms.cameras.models import AgentModel, CameraModel
from vms.edge.router import router as edge_router
from vms.event_clips.models import EventClipModel
from vms.events.models import VmsEventModel
from vms.iam.domain import ApiKeyOwnerType
from vms.iam.models import TenantModel
from vms.iam.repository import ApiKeyRepository
from vms.iam.service import ApiKeyService
from vms.infrastructure.exceptions import register_exception_handlers
from vms.shared.api.dependencies import get_db


class _FakeStorage:
    """Nenhum MinIO neste ambiente — guarda o que subiria."""

    def __init__(self) -> None:
        self.uploaded: list[tuple[str, str]] = []

    async def upload(self, local_path: str, key: str, content_type: str = "video/mp4") -> str:
        self.uploaded.append((local_path, key))
        return f"https://fake-storage.local/{key}"

    async def delete(self, key: str) -> None:
        return None


@pytest_asyncio.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> _FakeStorage:
    storage = _FakeStorage()
    monkeypatch.setattr(clip_service_module, "build_storage_provider", lambda: storage)
    return storage


@pytest_asyncio.fixture
async def agent_key(db_session: AsyncSession, tenant_a: TenantModel) -> str:
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
async def event_a(
    db_session: AsyncSession, tenant_a: TenantModel, camera_a: CameraModel
) -> VmsEventModel:
    event = VmsEventModel(
        id=str(uuid.uuid4()),
        tenant_id=tenant_a.id,
        camera_id=camera_a.id,
        event_type="intrusion.detected",
        occurred_at=datetime.now(UTC),
        payload={},
    )
    db_session.add(event)
    await db_session.flush()
    return event


@pytest_asyncio.fixture
async def event_of_other_tenant(
    db_session: AsyncSession, tenant_b: TenantModel
) -> VmsEventModel:
    event = VmsEventModel(
        id=str(uuid.uuid4()),
        tenant_id=tenant_b.id,
        camera_id=None,
        event_type="intrusion.detected",
        occurred_at=datetime.now(UTC),
        payload={},
    )
    db_session.add(event)
    await db_session.flush()
    return event


@pytest_asyncio.fixture
async def app(db_session: AsyncSession) -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(edge_router, prefix="/api/v1")
    register_exception_handlers(fastapi_app)
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


_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 512
_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048


class TestSnapshotUpload:
    async def test_snapshot_is_stored_and_linked_to_the_event(
        self, client: AsyncClient, db_session: AsyncSession,
        agent_key: str, event_a: VmsEventModel,
    ) -> None:
        resp = await client.put(
            f"/api/v1/edge/events/{event_a.id}/snapshot",
            headers={"Authorization": f"ApiKey {agent_key}"},
            files={"snapshot_file": ("snap.jpg", _JPEG, "image/jpeg")},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["snapshot_path"]

        await db_session.refresh(event_a)
        assert event_a.image_path == resp.json()["snapshot_path"]

    async def test_empty_file_is_refused(
        self, client: AsyncClient, agent_key: str, event_a: VmsEventModel
    ) -> None:
        resp = await client.put(
            f"/api/v1/edge/events/{event_a.id}/snapshot",
            headers={"Authorization": f"ApiKey {agent_key}"},
            files={"snapshot_file": ("snap.jpg", b"", "image/jpeg")},
        )
        assert resp.status_code == 422

    async def test_event_of_another_tenant_is_not_found(
        self, client: AsyncClient, agent_key: str, event_of_other_tenant: VmsEventModel
    ) -> None:
        """404 e não 403: dizer 'existe, mas não é seu' já vazaria que aquele
        ID é válido em algum lugar do sistema."""
        resp = await client.put(
            f"/api/v1/edge/events/{event_of_other_tenant.id}/snapshot",
            headers={"Authorization": f"ApiKey {agent_key}"},
            files={"snapshot_file": ("snap.jpg", _JPEG, "image/jpeg")},
        )
        assert resp.status_code == 404

    async def test_unknown_event_is_not_found(
        self, client: AsyncClient, agent_key: str
    ) -> None:
        resp = await client.put(
            f"/api/v1/edge/events/{uuid.uuid4()}/snapshot",
            headers={"Authorization": f"ApiKey {agent_key}"},
            files={"snapshot_file": ("snap.jpg", _JPEG, "image/jpeg")},
        )
        assert resp.status_code == 404


class TestClipUpload:
    async def test_clip_is_persisted_and_uploaded(
        self, client: AsyncClient, db_session: AsyncSession, fake_storage: _FakeStorage,
        agent_key: str, event_a: VmsEventModel, license_a: LicenseKeyModel,
    ) -> None:
        resp = await client.put(
            f"/api/v1/edge/events/{event_a.id}/clip",
            headers={"Authorization": f"ApiKey {agent_key}"},
            files={"clip_file": ("clip.mp4", _MP4, "video/mp4")},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "uploaded"
        assert len(fake_storage.uploaded) == 1

        clip = await db_session.get(EventClipModel, resp.json()["clip_id"])
        # tenant_id e size_bytes são o que a cota soma — sem eles ela não teria
        # como responder "quanto este cliente já ocupa?" (migration 0015).
        assert clip.tenant_id == event_a.tenant_id
        assert clip.size_bytes == len(_MP4)

    async def test_over_quota_returns_413(
        self, client: AsyncClient, db_session: AsyncSession, fake_storage: _FakeStorage,
        agent_key: str, event_a: VmsEventModel, license_a: LicenseKeyModel,
    ) -> None:
        license_a.storage_quota_mb = 1
        db_session.add(EventClipModel(
            id=str(uuid.uuid4()),
            vms_event_id=str(uuid.uuid4()),
            tenant_id=event_a.tenant_id,
            size_bytes=2 * 1024 * 1024,  # já passou de 1 MB
            status="uploaded",
        ))
        await db_session.flush()

        resp = await client.put(
            f"/api/v1/edge/events/{event_a.id}/clip",
            headers={"Authorization": f"ApiKey {agent_key}"},
            files={"clip_file": ("clip.mp4", _MP4, "video/mp4")},
        )

        assert resp.status_code == 413
        assert fake_storage.uploaded == []

    async def test_over_quota_keeps_the_event_and_its_snapshot(
        self, client: AsyncClient, db_session: AsyncSession, fake_storage: _FakeStorage,
        agent_key: str, event_a: VmsEventModel, license_a: LicenseKeyModel,
    ) -> None:
        """Recusar só o clipe é deliberado: o cliente continua enxergando o que
        aconteceu e recebendo alerta — perde a evidência em vídeo, que é o item
        caro, não o registro."""
        license_a.storage_quota_mb = 1
        db_session.add(EventClipModel(
            id=str(uuid.uuid4()), vms_event_id=str(uuid.uuid4()),
            tenant_id=event_a.tenant_id, size_bytes=5 * 1024 * 1024, status="uploaded",
        ))
        await db_session.flush()

        snapshot = await client.put(
            f"/api/v1/edge/events/{event_a.id}/snapshot",
            headers={"Authorization": f"ApiKey {agent_key}"},
            files={"snapshot_file": ("snap.jpg", _JPEG, "image/jpeg")},
        )
        clip = await client.put(
            f"/api/v1/edge/events/{event_a.id}/clip",
            headers={"Authorization": f"ApiKey {agent_key}"},
            files={"clip_file": ("clip.mp4", _MP4, "video/mp4")},
        )

        assert snapshot.status_code == 200
        assert clip.status_code == 413
        await db_session.refresh(event_a)
        assert event_a.image_path is not None

    async def test_quota_zero_means_unlimited(
        self, client: AsyncClient, db_session: AsyncSession, fake_storage: _FakeStorage,
        agent_key: str, event_a: VmsEventModel, license_a: LicenseKeyModel,
    ) -> None:
        """Usado por clientes internos/demonstração."""
        license_a.storage_quota_mb = 0
        db_session.add(EventClipModel(
            id=str(uuid.uuid4()), vms_event_id=str(uuid.uuid4()),
            tenant_id=event_a.tenant_id, size_bytes=500 * 1024 * 1024, status="uploaded",
        ))
        await db_session.flush()

        resp = await client.put(
            f"/api/v1/edge/events/{event_a.id}/clip",
            headers={"Authorization": f"ApiKey {agent_key}"},
            files={"clip_file": ("clip.mp4", _MP4, "video/mp4")},
        )
        assert resp.status_code == 200

    async def test_quota_is_isolated_per_tenant(
        self, client: AsyncClient, db_session: AsyncSession, fake_storage: _FakeStorage,
        agent_key: str, event_a: VmsEventModel, license_a: LicenseKeyModel,
        tenant_b: TenantModel,
    ) -> None:
        """O consumo do vizinho não pode contar contra este cliente."""
        license_a.storage_quota_mb = 1
        db_session.add(EventClipModel(
            id=str(uuid.uuid4()), vms_event_id=str(uuid.uuid4()),
            tenant_id=tenant_b.id, size_bytes=900 * 1024 * 1024, status="uploaded",
        ))
        await db_session.flush()

        resp = await client.put(
            f"/api/v1/edge/events/{event_a.id}/clip",
            headers={"Authorization": f"ApiKey {agent_key}"},
            files={"clip_file": ("clip.mp4", _MP4, "video/mp4")},
        )
        assert resp.status_code == 200

    async def test_event_of_another_tenant_is_not_found(
        self, client: AsyncClient, fake_storage: _FakeStorage,
        agent_key: str, event_of_other_tenant: VmsEventModel,
    ) -> None:
        resp = await client.put(
            f"/api/v1/edge/events/{event_of_other_tenant.id}/clip",
            headers={"Authorization": f"ApiKey {agent_key}"},
            files={"clip_file": ("clip.mp4", _MP4, "video/mp4")},
        )
        assert resp.status_code == 404

    async def test_resending_the_same_clip_is_idempotent(
        self, client: AsyncClient, fake_storage: _FakeStorage,
        agent_key: str, event_a: VmsEventModel, license_a: LicenseKeyModel,
    ) -> None:
        """Reenvio do worker de edge depois de uma confirmação perdida na rede
        não pode gerar um segundo objeto no storage."""
        headers = {"Authorization": f"ApiKey {agent_key}"}
        files = {"clip_file": ("clip.mp4", _MP4, "video/mp4")}

        first = await client.put(f"/api/v1/edge/events/{event_a.id}/clip", headers=headers, files=files)
        second = await client.put(f"/api/v1/edge/events/{event_a.id}/clip", headers=headers, files=files)

        assert first.json()["clip_id"] == second.json()["clip_id"]
        assert len(fake_storage.uploaded) == 1
