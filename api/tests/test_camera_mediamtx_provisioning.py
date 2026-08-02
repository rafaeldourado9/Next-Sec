"""Câmera de agent não é provisionada no MediaMTX central (ADR-019 §1).

Bug real de produção, achado em 2026-08-02 nos logs do MediaMTX da VPS:

    ERR [path tenant-.../cam-...] [RTSP source]
        dial tcp 192.168.0.101:554: i/o timeout

Ao criar uma câmera `rtsp_pull` vinculada a um agent, a API provisionava um
path no MediaMTX **central** com `source` apontando para o RTSP da câmera —
um IP de LAN que a VPS nunca alcança. O resultado eram duas coisas ruins ao
mesmo tempo: um loop infinito de timeout nos logs, e duas conexões RTSP
simultâneas disputando a mesma câmera (o agent, corretamente de dentro da
LAN; a VPS, inutilmente de fora) — sendo que muitos modelos domésticos não
toleram bem dois clientes.

Havia **zero teste** cobrindo o provisionamento no MediaMTX antes disto.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from vms.cameras.domain import StreamProtocol
from vms.cameras.repository import CameraRepository
from vms.cameras.service import CameraService
from vms.iam.models import TenantModel


@dataclass
class _FakeMediaMTX:
    """Registra as chamadas em vez de falar com um MediaMTX real."""

    added: list[dict] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    async def add_path(self, path: str, source_url: str = "", **kwargs) -> bool:
        self.added.append({"path": path, "source_url": source_url, **kwargs})
        return True

    async def remove_path(self, path: str) -> bool:
        self.removed.append(path)
        return True


@pytest_asyncio.fixture
async def mediamtx() -> _FakeMediaMTX:
    return _FakeMediaMTX()


@pytest_asyncio.fixture
async def service(db_session: AsyncSession, mediamtx: _FakeMediaMTX) -> CameraService:
    return CameraService(CameraRepository(db_session), mediamtx=mediamtx)


@pytest_asyncio.fixture(autouse=True)
def _no_agent_notification(monkeypatch: pytest.MonkeyPatch):
    """`_notify_agent` publica no Redis — irrelevante aqui e indisponível."""
    async def _noop(*args, **kwargs):
        return None

    import vms.cameras.service as service_module

    monkeypatch.setattr(service_module, "_notify_agent", _noop)


_LAN_RTSP = "rtsp://admin:senha@192.168.0.101:554/Streaming/Channels/101"


class TestAgentCameraIsNotProvisionedCentrally:
    async def test_camera_with_agent_creates_no_central_path(
        self, service: CameraService, mediamtx: _FakeMediaMTX, tenant_a: TenantModel
    ) -> None:
        """A regressão exata: nenhum path central para câmera de agent."""
        await service.create_camera(
            tenant_id=tenant_a.id,
            name="Câmera da loja",
            rtsp_url=_LAN_RTSP,
            agent_id=str(uuid.uuid4()),
            stream_protocol=StreamProtocol.RTSP_PULL,
        )

        assert mediamtx.added == []

    async def test_lan_address_never_reaches_the_central_mediamtx(
        self, service: CameraService, mediamtx: _FakeMediaMTX, tenant_a: TenantModel
    ) -> None:
        """Formulação complementar, ancorada no sintoma: o IP de LAN que
        aparecia no `dial tcp ... i/o timeout` não pode chegar ao MediaMTX
        central de forma nenhuma."""
        await service.create_camera(
            tenant_id=tenant_a.id,
            name="Câmera da loja",
            rtsp_url=_LAN_RTSP,
            agent_id=str(uuid.uuid4()),
            stream_protocol=StreamProtocol.RTSP_PULL,
        )

        assert all("192.168.0.101" not in c.get("source_url", "") for c in mediamtx.added)

    async def test_updating_the_rtsp_url_still_does_not_provision(
        self, service: CameraService, mediamtx: _FakeMediaMTX, tenant_a: TenantModel
    ) -> None:
        """Editar a câmera não pode reintroduzir o path pela porta dos fundos."""
        camera = await service.create_camera(
            tenant_id=tenant_a.id,
            name="Câmera da loja",
            rtsp_url=_LAN_RTSP,
            agent_id=str(uuid.uuid4()),
            stream_protocol=StreamProtocol.RTSP_PULL,
        )

        await service.update_camera(
            camera_id=camera.id,
            tenant_id=tenant_a.id,
            rtsp_url="rtsp://admin:senha@192.168.0.102:554/Streaming/Channels/101",
        )

        assert mediamtx.added == []

    async def test_deleting_still_removes_the_path(
        self, service: CameraService, mediamtx: _FakeMediaMTX, tenant_a: TenantModel
    ) -> None:
        """`remove_path` é deliberadamente incondicional: câmeras criadas
        ANTES desta mudança têm path central mesmo sendo de agent, e ficariam
        órfãs no MediaMTX se a remoção passasse a ser condicional."""
        camera = await service.create_camera(
            tenant_id=tenant_a.id,
            name="Câmera da loja",
            rtsp_url=_LAN_RTSP,
            agent_id=str(uuid.uuid4()),
            stream_protocol=StreamProtocol.RTSP_PULL,
        )

        await service.delete_camera(camera.id, tenant_a.id)

        assert camera.mediamtx_path in mediamtx.removed


class TestCameraWithoutAgentIsUnchanged:
    """Nível 3 (a própria VPS ingere de uma câmera alcançável) não pode ter
    regredido — é o caminho que ainda usa o MediaMTX central."""

    async def test_camera_without_agent_is_provisioned_with_its_source(
        self, service: CameraService, mediamtx: _FakeMediaMTX, tenant_a: TenantModel
    ) -> None:
        public_rtsp = "rtsp://cam.exemplo.com:554/stream1"

        camera = await service.create_camera(
            tenant_id=tenant_a.id,
            name="Câmera com IP público",
            rtsp_url=public_rtsp,
            stream_protocol=StreamProtocol.RTSP_PULL,
        )

        assert len(mediamtx.added) == 1
        assert mediamtx.added[0]["path"] == camera.mediamtx_path
        assert mediamtx.added[0]["source_url"] == public_rtsp

    async def test_updating_rtsp_url_reprovisions(
        self, service: CameraService, mediamtx: _FakeMediaMTX, tenant_a: TenantModel
    ) -> None:
        camera = await service.create_camera(
            tenant_id=tenant_a.id,
            name="Câmera com IP público",
            rtsp_url="rtsp://cam.exemplo.com:554/stream1",
            stream_protocol=StreamProtocol.RTSP_PULL,
        )
        mediamtx.added.clear()

        await service.update_camera(
            camera_id=camera.id,
            tenant_id=tenant_a.id,
            rtsp_url="rtsp://cam.exemplo.com:554/stream2",
        )

        assert len(mediamtx.added) == 1
        assert mediamtx.added[0]["source_url"] == "rtsp://cam.exemplo.com:554/stream2"


class TestIsEdgeManaged:
    """A propriedade que centraliza a regra — usada em 4 lugares
    (`service.create/update`, `tasks.py`, `main.py`)."""

    async def test_true_when_the_camera_has_an_agent(
        self, service: CameraService, tenant_a: TenantModel
    ) -> None:
        camera = await service.create_camera(
            tenant_id=tenant_a.id, name="c", rtsp_url=_LAN_RTSP,
            agent_id=str(uuid.uuid4()), stream_protocol=StreamProtocol.RTSP_PULL,
        )
        assert camera.is_edge_managed is True

    async def test_false_without_an_agent(
        self, service: CameraService, tenant_a: TenantModel
    ) -> None:
        camera = await service.create_camera(
            tenant_id=tenant_a.id, name="c", rtsp_url="rtsp://cam.exemplo.com/s",
            stream_protocol=StreamProtocol.RTSP_PULL,
        )
        assert camera.is_edge_managed is False
