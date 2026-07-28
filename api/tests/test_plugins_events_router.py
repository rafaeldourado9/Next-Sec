"""Testes HTTP do contrato público de plugins — `POST /plugins/events` e
`PUT /plugins/events/{id}/clip` (ver ADR-017 §1, Sprint 6 — S6-03).

Sobe só o router de plugins num `FastAPI` mínimo (sem lifespan/Postgres/Redis
reais — mesmo espírito de isolamento dos demais testes desta suíte, que não
sobem docker compose), via `httpx.ASGITransport`, com a dependência de sessão
de banco sobrescrita para o SQLite em memória do `conftest.py`. Isso exercita
o parsing HTTP de verdade (JSON vs multipart) — a parte nova de maior risco
desta sprint (endpoint único que aceita os dois formatos de corpo) — sem
precisar de infraestrutura real.
"""
from __future__ import annotations

import json
import uuid

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from vms.cameras.models import CameraModel
from vms.iam.models import TenantModel, UserModel
from vms.plugins.router import router as plugins_router
from vms.shared.api.dependencies import get_db

_HEADERS = {"Authorization": "ApiKey dev-analytics-key"}


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession, tenant_a: TenantModel) -> UserModel:
    """Necessário pro fast-path de API key do analytics em `_resolve_plugin_
    tenant`, que busca 'algum admin' do banco pra resolver o tenant da chave
    de ambiente `VMS_API_KEY` (default 'dev-analytics-key')."""
    user = UserModel(
        id=str(uuid.uuid4()), tenant_id=tenant_a.id, email="admin@test.local",
        hashed_password="x", full_name="Admin", role="admin", is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def app(db_session: AsyncSession, admin_user: UserModel) -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(plugins_router, prefix="/api/v1")

    async def _override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    return fastapi_app


@pytest_asyncio.fixture
async def client(app: FastAPI):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestIngestEventJson:
    """Compatibilidade retroativa: POST JSON puro continua idêntico (Nível 3)."""

    async def test_json_only_event_is_created_as_before(
        self, client: AsyncClient, camera_a: CameraModel
    ) -> None:
        resp = await client.post(
            "/api/v1/plugins/events",
            headers=_HEADERS,
            json={
                "camera_id": camera_a.id,
                "event_type": "intrusion.detected",
                "payload": {"class": "person"},
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["id"]

    async def test_unknown_camera_returns_404(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/plugins/events",
            headers=_HEADERS,
            json={"camera_id": "does-not-exist", "event_type": "x", "payload": {}},
        )
        assert resp.status_code == 404

    async def test_invalid_json_returns_422(self, client: AsyncClient) -> None:
        resp = await client.request(
            "POST", "/api/v1/plugins/events",
            headers={**_HEADERS, "Content-Type": "application/json"},
            content=b"{not valid json",
        )
        assert resp.status_code == 422


class TestIngestEventMultipart:
    """Nível 1 (edge, Docker dedicado no cliente): multipart com snapshot
    inline — ver ADR-017 §1."""

    async def test_multipart_snapshot_is_saved_and_used_as_snapshot_path(
        self, client: AsyncClient, camera_a: CameraModel, tmp_path, monkeypatch
    ) -> None:
        import vms.events.images as images_module

        monkeypatch.setattr(images_module, "SNAPSHOTS_DIR", tmp_path)

        payload = {
            "camera_id": camera_a.id,
            "event_type": "intrusion.detected",
            "payload": {"class": "person"},
            "edge_generates_clip": True,
        }
        files = {"snapshot_file": ("frame.jpg", b"\xff\xd8\xff-fake-jpeg-bytes", "image/jpeg")}
        data = {"payload": json.dumps(payload)}

        resp = await client.post(
            "/api/v1/plugins/events", headers=_HEADERS, data=data, files=files,
        )
        assert resp.status_code == 201

        saved_files = list(tmp_path.rglob("*.jpg"))
        assert len(saved_files) == 1
        assert saved_files[0].read_bytes() == b"\xff\xd8\xff-fake-jpeg-bytes"
        assert camera_a.tenant_id in str(saved_files[0])

    async def test_multipart_without_payload_field_returns_422(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/v1/plugins/events",
            headers=_HEADERS,
            files={"snapshot_file": ("x.jpg", b"abc", "image/jpeg")},
        )
        assert resp.status_code == 422

    async def test_multipart_invalid_payload_json_returns_422(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/v1/plugins/events",
            headers=_HEADERS,
            data={"payload": "{not valid json"},
            files={"snapshot_file": ("x.jpg", b"abc", "image/jpeg")},
        )
        assert resp.status_code == 422


class TestReceivePregeneratedClip:
    """`PUT /plugins/events/{id}/clip` — ver ADR-017 §1 e
    `EventClipService.receive_pregenerated_clip`."""

    async def test_put_clip_persists_and_marks_uploaded(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        tenant_a: TenantModel,
        camera_a: CameraModel,
        monkeypatch,
    ) -> None:
        from vms.event_clips import service as service_module
        from vms.events.models import VmsEventModel

        event = VmsEventModel(
            id=str(uuid.uuid4()), tenant_id=tenant_a.id, camera_id=camera_a.id,
            event_type="intrusion.detected", payload={},
        )
        db_session.add(event)
        await db_session.flush()

        class FakeStorageProvider:
            def __init__(self) -> None:
                self.uploaded: dict[str, str] = {}

            async def upload(self, local_path: str, key: str, content_type: str) -> str:
                self.uploaded[key] = local_path
                return f"https://fake-storage.local/{key}"

            async def delete(self, key: str) -> None:
                self.uploaded.pop(key, None)

        fake_storage = FakeStorageProvider()
        monkeypatch.setattr(
            service_module,
            "build_event_clip_service",
            lambda session: service_module.EventClipService(
                clip_repo=service_module.EventClipRepository(session),
                session=session,
                storage=fake_storage,
            ),
        )

        resp = await client.put(
            f"/api/v1/plugins/events/{event.id}/clip",
            headers=_HEADERS,
            files={"clip_file": ("clip.mp4", b"fake-mp4-bytes", "video/mp4")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "uploaded"
        assert len(fake_storage.uploaded) == 1

    async def test_put_clip_unknown_event_returns_404(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/api/v1/plugins/events/does-not-exist/clip",
            headers=_HEADERS,
            files={"clip_file": ("clip.mp4", b"x", "video/mp4")},
        )
        assert resp.status_code == 404

    async def test_put_clip_rejects_api_key_from_another_tenant(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        tenant_a: TenantModel,
        tenant_b: TenantModel,
        camera_a: CameraModel,
        monkeypatch,
    ) -> None:
        """Isolamento de tenant (ver test-contracts.md TC-005 / ADR-017 §1):
        uma API key válida do tenant B nunca pode anexar um clipe a um evento
        que pertence ao tenant A, mesmo que o `event_id` (UUID) vaze de algum
        jeito (log, erro, etc.) — cada cliente Nível 1 tem sua própria API
        key (ver `.env.edge.example`), então este é exatamente o cenário que
        separaria um cliente do outro caso um deles seja comprometido.

        Achado durante a auditoria de S6-06: `receive_pregenerated_event_clip`
        chama `_resolve_plugin_tenant` só para validar que a API key existe,
        mas descarta o tenant_id retornado e resolve o tenant do evento
        direto da tabela `vms_events` — sem comparar os dois. Corrigido nesta
        mesma task (ver `router.py`)."""
        import uuid as _uuid

        from vms.events.models import VmsEventModel
        from vms.iam.models import ApiKeyModel
        from vms.infrastructure.security import generate_api_key

        plain_key, key_hash, prefix = generate_api_key()
        db_session.add(
            ApiKeyModel(
                id=str(_uuid.uuid4()),
                tenant_id=tenant_b.id,
                owner_type="agent",
                owner_id=str(_uuid.uuid4()),
                key_hash=key_hash,
                prefix=prefix,
                is_active=True,
            )
        )

        event = VmsEventModel(
            id=str(_uuid.uuid4()), tenant_id=tenant_a.id, camera_id=camera_a.id,
            event_type="intrusion.detected", payload={},
        )
        db_session.add(event)
        await db_session.flush()

        resp = await client.put(
            f"/api/v1/plugins/events/{event.id}/clip",
            headers={"Authorization": f"ApiKey {plain_key}"},
            files={"clip_file": ("clip.mp4", b"fake-mp4-bytes", "video/mp4")},
        )
        assert resp.status_code == 404
