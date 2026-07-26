"""Testes de watchlist (face_profiles) — ver .genesis/contracts/test-contracts.md."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vms.iam.models import TenantModel
from vms.shared.exceptions import NotFoundError, UnauthorizedError
from vms.watchlist.service import WatchlistService
from vms.watchlist.repository import FaceProfileRepository


class FakeObjectStorage:
    """Storage em memória — evita depender de um MinIO real nos testes."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def upload_bytes(self, bucket: str, key: str, data: bytes, content_type: str = "") -> None:
        self.objects[(bucket, key)] = data

    def delete_object(self, bucket: str, key: str) -> None:
        self.objects.pop((bucket, key), None)

    def get_presigned_url(self, bucket: str, key: str, expires: int = 3600) -> str:
        return f"https://fake-storage.local/{bucket}/{key}"


def _svc(session: AsyncSession, storage: FakeObjectStorage) -> WatchlistService:
    return WatchlistService(
        profile_repo=FaceProfileRepository(session), session=session, storage=storage,
    )


class TestLGPDGate:
    async def test_create_without_consent_raises_unauthorized(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        assert tenant_a.facial_recognition_enabled is False
        svc = _svc(db_session, FakeObjectStorage())
        with pytest.raises(UnauthorizedError):
            await svc.create_profile(
                tenant_id=tenant_a.id, name="João", image_bytes=b"fake-jpeg", content_type="image/jpeg",
            )

    async def test_create_with_consent_succeeds(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        tenant_a.facial_recognition_enabled = True
        await db_session.flush()

        storage = FakeObjectStorage()
        svc = _svc(db_session, storage)
        profile = await svc.create_profile(
            tenant_id=tenant_a.id, name="João", image_bytes=b"fake-jpeg", content_type="image/jpeg",
        )
        assert profile.name == "João"
        assert profile.reference_image_path is not None
        # Imagem foi de fato enviada ao storage (fake)
        assert any(profile.reference_image_path in key for _, key in storage.objects)


class TestWatchlistLifecycle:
    async def test_soft_delete_removes_image_from_storage(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        tenant_a.facial_recognition_enabled = True
        await db_session.flush()

        storage = FakeObjectStorage()
        svc = _svc(db_session, storage)
        profile = await svc.create_profile(
            tenant_id=tenant_a.id, name="João", image_bytes=b"fake-jpeg", content_type="image/jpeg",
        )
        assert len(storage.objects) == 1

        await svc.delete_profile(profile.id, tenant_a.id)
        assert len(storage.objects) == 0

        profiles = await svc.list_profiles(tenant_a.id)
        assert profile.id not in [p.id for p in profiles]

    async def test_delete_nonexistent_profile_raises_not_found(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        svc = _svc(db_session, FakeObjectStorage())
        with pytest.raises(NotFoundError):
            await svc.delete_profile("does-not-exist", tenant_a.id)


class TestMultiTenantIsolation:
    async def test_tenant_cannot_delete_other_tenants_profile(
        self, db_session: AsyncSession, tenant_a: TenantModel, tenant_b: TenantModel
    ) -> None:
        tenant_b.facial_recognition_enabled = True
        await db_session.flush()

        svc = _svc(db_session, FakeObjectStorage())
        profile_b = await svc.create_profile(
            tenant_id=tenant_b.id, name="Bia", image_bytes=b"fake-jpeg", content_type="image/jpeg",
        )
        with pytest.raises(NotFoundError):
            await svc.delete_profile(profile_b.id, tenant_a.id)
