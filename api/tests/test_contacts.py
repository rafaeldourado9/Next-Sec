"""Testes de contacts — ver .genesis/contracts/test-contracts.md."""
from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from vms.cameras.models import CameraModel
from vms.contacts.schemas import CreateContactRequest
from vms.contacts.service import ContactService, build_contact_service
from vms.iam.models import TenantModel
from vms.shared.exceptions import NotFoundError


def _svc(session: AsyncSession) -> ContactService:
    return build_contact_service(session)


class TestPhoneValidation:
    def test_rejects_phone_without_plus(self) -> None:
        with pytest.raises(ValidationError):
            CreateContactRequest(phone_number="5511999999999", name="Ana")

    def test_accepts_e164_phone(self) -> None:
        req = CreateContactRequest(phone_number="+5511999999999", name="Ana")
        assert req.phone_number == "+5511999999999"


class TestCreateContact:
    async def test_camera_id_none_means_all_cameras(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        contact = await _svc(db_session).create_contact(
            tenant_id=tenant_a.id, phone_number="+5511999999999", name="Ana", camera_id=None,
        )
        assert contact.camera_id is None
        assert contact.is_active is True

    async def test_camera_from_other_tenant_raises_not_found(
        self, db_session: AsyncSession, tenant_a: TenantModel, tenant_b: TenantModel
    ) -> None:
        other_camera = CameraModel(id="cam-b-1", tenant_id=tenant_b.id, name="Câmera do Tenant B")
        db_session.add(other_camera)
        await db_session.flush()

        with pytest.raises(NotFoundError):
            await _svc(db_session).create_contact(
                tenant_id=tenant_a.id,
                phone_number="+5511999999999",
                name="Ana",
                camera_id=other_camera.id,
            )

    async def test_camera_from_same_tenant_succeeds(
        self, db_session: AsyncSession, tenant_a: TenantModel, camera_a: CameraModel
    ) -> None:
        contact = await _svc(db_session).create_contact(
            tenant_id=tenant_a.id,
            phone_number="+5511999999999",
            name="Ana",
            camera_id=camera_a.id,
        )
        assert contact.camera_id == camera_a.id


class TestContactLifecycle:
    async def test_deactivate_contact(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        svc = _svc(db_session)
        contact = await svc.create_contact(
            tenant_id=tenant_a.id, phone_number="+5511999999999", name="Ana", camera_id=None,
        )
        updated = await svc.update_contact(contact.id, tenant_a.id, is_active=False)
        assert updated.is_active is False

    async def test_soft_delete_contact(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        svc = _svc(db_session)
        contact = await svc.create_contact(
            tenant_id=tenant_a.id, phone_number="+5511999999999", name="Ana", camera_id=None,
        )
        await svc.delete_contact(contact.id, tenant_a.id)

        # Removido não aparece mais em listagens nem é encontrável
        contacts = await svc.list_contacts(tenant_a.id, camera_id=None)
        assert contact.id not in [c.id for c in contacts]


class TestMultiTenantIsolation:
    async def test_tenant_cannot_update_other_tenants_contact(
        self, db_session: AsyncSession, tenant_a: TenantModel, tenant_b: TenantModel
    ) -> None:
        svc = _svc(db_session)
        contact_b = await svc.create_contact(
            tenant_id=tenant_b.id, phone_number="+5511999999999", name="Bia", camera_id=None,
        )
        with pytest.raises(NotFoundError):
            await svc.update_contact(contact_b.id, tenant_a.id, name="Hacked")

    async def test_tenant_cannot_delete_other_tenants_contact(
        self, db_session: AsyncSession, tenant_a: TenantModel, tenant_b: TenantModel
    ) -> None:
        svc = _svc(db_session)
        contact_b = await svc.create_contact(
            tenant_id=tenant_b.id, phone_number="+5511999999999", name="Bia", camera_id=None,
        )
        with pytest.raises(NotFoundError):
            await svc.delete_contact(contact_b.id, tenant_a.id)
