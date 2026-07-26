"""Testes de event_clips — geração e upload do clipe (ver test-contracts.md)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vms.event_clips.domain import ClipStatus
from vms.event_clips.repository import EventClipRepository
from vms.event_clips.service import EventClipService
from vms.events.models import VmsEventModel
from vms.iam.models import TenantModel
from vms.shared.exceptions import NotFoundError


class FakeStorageProvider:
    """StorageProvider em memória — evita depender de MinIO real nos testes."""

    def __init__(self) -> None:
        self.uploaded: dict[str, str] = {}

    async def upload(self, local_path: str, key: str, content_type: str) -> str:
        self.uploaded[key] = local_path
        return f"https://fake-storage.local/{key}"

    async def delete(self, key: str) -> None:
        self.uploaded.pop(key, None)


async def _make_event(session: AsyncSession, tenant: TenantModel, *, image_path: str | None) -> str:
    event = VmsEventModel(
        id=str(uuid.uuid4()), tenant_id=tenant.id, event_type="analytics.intrusion.crossed",
        image_path=image_path, payload={},
    )
    session.add(event)
    await session.flush()
    return event.id


def _svc(session: AsyncSession, storage: FakeStorageProvider) -> EventClipService:
    return EventClipService(clip_repo=EventClipRepository(session), session=session, storage=storage)


class TestGenerateAndUpload:
    async def test_no_snapshot_marks_failed(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        event_id = await _make_event(db_session, tenant_a, image_path=None)
        clip = await _svc(db_session, FakeStorageProvider()).generate_and_upload(
            event_id, tenant_a.id, image_path=None
        )
        assert clip.status == ClipStatus.FAILED
        assert "snapshot" in (clip.error_message or "").lower()

    async def test_missing_file_marks_failed(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        event_id = await _make_event(db_session, tenant_a, image_path="events/does/not/exist.jpg")
        clip = await _svc(db_session, FakeStorageProvider()).generate_and_upload(
            event_id, tenant_a.id, image_path="events/does/not/exist.jpg"
        )
        assert clip.status == ClipStatus.FAILED
        assert "não encontrado" in (clip.error_message or "").lower()

    async def test_idempotent_returns_existing_clip(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        event_id = await _make_event(db_session, tenant_a, image_path=None)
        svc = _svc(db_session, FakeStorageProvider())
        first = await svc.generate_and_upload(event_id, tenant_a.id, image_path=None)
        second = await svc.generate_and_upload(event_id, tenant_a.id, image_path=None)
        assert first.id == second.id


class TestGetClip:
    async def test_get_clip_raises_not_found_when_missing(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        with pytest.raises(NotFoundError):
            await _svc(db_session, FakeStorageProvider()).get_clip("does-not-exist")
