"""Testes de `task_dispatch_event_notifications` — split clipe/notificação
(ver ADR-017 §1, Sprint 6 — S6-03): quando `edge_generates_clip=True`, a task
não deve gerar clipe via ffmpeg (`EventClipService.generate_and_upload` nunca
é chamado) — o worker de edge local já cuida disso — mas a notificação
(`evaluate_and_dispatch`) continua rodando normalmente, exatamente como hoje.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vms.iam.models import TenantModel
from vms.notifications import tasks as tasks_module

pytestmark = pytest.mark.asyncio


class _CountingEventClipServiceFactory:
    """Substitui `build_event_clip_service` — registra quantas vezes o
    serviço foi construído (proxy de "ffmpeg teria rodado")."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, db):
        self.calls += 1

        class _Never:
            async def generate_and_upload(self, **kwargs):  # pragma: no cover
                raise AssertionError("generate_and_upload não deveria ser chamado")

        return _Never()


class _RecordingNotificationServiceFactory:
    """Substitui `build_notification_service` — captura os argumentos do
    `evaluate_and_dispatch` para asserção."""

    def __init__(self) -> None:
        self.dispatched: list[dict] = []

    def __call__(self, db):
        outer = self

        class _Recorder:
            async def evaluate_and_dispatch(self, **kwargs):
                outer.dispatched.append(kwargs)
                return []

        return _Recorder()


class TestEdgeGeneratesClip:
    async def test_edge_flag_skips_clip_generation_but_still_notifies(
        self, db_session: AsyncSession, tenant_a: TenantModel, monkeypatch
    ) -> None:
        import vms.event_clips.service as clip_service_module
        import vms.notifications.service as notif_service_module

        clip_factory = _CountingEventClipServiceFactory()
        notif_factory = _RecordingNotificationServiceFactory()
        monkeypatch.setattr(clip_service_module, "build_event_clip_service", clip_factory)
        monkeypatch.setattr(notif_service_module, "build_notification_service", notif_factory)

        event_id = str(uuid.uuid4())
        await tasks_module.task_dispatch_event_notifications(
            ctx={},
            tenant_id=tenant_a.id,
            event_type="analytics.intrusion.crossed",
            event_id=event_id,
            payload={"class": "person"},
            snapshot_path="tenant-x/cam-y/2026-07-28/does-not-exist.jpg",
            camera_id=None,
            edge_generates_clip=True,
        )

        assert clip_factory.calls == 0, "ffmpeg não deveria rodar para eventos de edge"
        assert len(notif_factory.dispatched) == 1
        assert notif_factory.dispatched[0]["event_id"] == event_id
        assert notif_factory.dispatched[0]["tenant_id"] == tenant_a.id

    async def test_edge_flag_false_still_generates_clip_as_before(
        self, db_session: AsyncSession, tenant_a: TenantModel, monkeypatch
    ) -> None:
        import vms.event_clips.service as clip_service_module
        import vms.notifications.service as notif_service_module

        clip_factory = _CountingEventClipServiceFactory()
        # Nesta variante o generate_and_upload real seria chamado — usamos um
        # dummy que não levanta, só pra confirmar que o factory É invocado
        # (comportamento pré-S6-03 preservado quando edge_generates_clip=False).
        class _Dummy:
            async def generate_and_upload(self, **kwargs):
                return None

        def factory(db):
            clip_factory.calls += 1
            return _Dummy()

        notif_factory = _RecordingNotificationServiceFactory()
        monkeypatch.setattr(clip_service_module, "build_event_clip_service", factory)
        monkeypatch.setattr(notif_service_module, "build_notification_service", notif_factory)

        event_id = str(uuid.uuid4())
        await tasks_module.task_dispatch_event_notifications(
            ctx={},
            tenant_id=tenant_a.id,
            event_type="analytics.intrusion.crossed",
            event_id=event_id,
            payload={},
            snapshot_path="tenant-x/cam-y/2026-07-28/does-not-exist.jpg",
            camera_id=None,
            edge_generates_clip=False,
        )

        assert clip_factory.calls == 1
        assert len(notif_factory.dispatched) == 1

    async def test_no_snapshot_skips_everything(
        self, db_session: AsyncSession, tenant_a: TenantModel, monkeypatch
    ) -> None:
        import vms.event_clips.service as clip_service_module
        import vms.notifications.service as notif_service_module

        clip_factory = _CountingEventClipServiceFactory()
        notif_factory = _RecordingNotificationServiceFactory()
        monkeypatch.setattr(clip_service_module, "build_event_clip_service", clip_factory)
        monkeypatch.setattr(notif_service_module, "build_notification_service", notif_factory)

        await tasks_module.task_dispatch_event_notifications(
            ctx={},
            tenant_id=tenant_a.id,
            event_type="analytics.intrusion.crossed",
            event_id=str(uuid.uuid4()),
            payload={},
            snapshot_path=None,
            camera_id=None,
            edge_generates_clip=True,
        )

        assert clip_factory.calls == 0
        assert notif_factory.dispatched == []
